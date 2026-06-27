from __future__ import annotations
 
import json
from typing import List, Optional, Sequence
 
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict
from redis.asyncio import Redis
 
from app.config import get_settings
from app.logger import logging
 
logger = logging.getLogger(__name__)
 
# redis key will be like this: chat:{session_id}
HISTORY_KEY_PREFIX = "chat:"

class RedisMessageHistory(BaseChatMessageHistory):
    """
    A LangChain BaseChatMessageHistory backed by a Redis list.
 
    Stores the conversation's message history for one session as a
    Redis list at key "chat:{session_id}". The list is capped at
    REDIS_HISTORY_WINDOW messages (sliding window) and refreshed
    to SESSION_TTL_MINUTES TTL on every write.
 
    Parameters
    ----------
    session_id     The conversation session identifier. Used as the
                   suffix of the Redis key: "chat:{session_id}".
    redis_client   An async redis.asyncio.Redis client. The caller
                   is responsible for the client lifecycle (opening
                   and closing the connection pool).
    window_size    Maximum number of messages to retain (default:
                   settings.redis.REDIS_HISTORY_WINDOW, usually 20).
    ttl_minutes    Idle TTL in minutes (default:
                   settings.redis.SESSION_TTL_MINUTES, usually 30).
                   Refreshed on every write.
    """
    
    def __init__(
        self,
        session_id: str,
        redis_client: Redis,
        window_size: Optional[int] = None,
        ttl_minutes: Optional[int] = None,
    ) -> None:
        cfg = get_settings().redis
        self.session_id = session_id.strip()
        self.redis = redis_client
        self.window_size = window_size if window_size is not None else cfg.REDIS_HISTORY_WINDOW
        self.ttl_seconds = (ttl_minutes if ttl_minutes is not None else cfg.SESSION_TTL_MINUTES) * 60
        self._key = f"{HISTORY_KEY_PREFIX}{self.session_id}"
        
    @property
    def messages(self) -> List[BaseMessage]:
        """
        Synchronous interface required by BaseChatMessageHistory.
        
        Fetches the last window_size messages from the Redis list.
        Prefer agent_messages() in async call sites.
        """
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers = 1) as pool:
                    future = pool.submit(asyncio.run, self.agent_messages())
                    return future.result()
        except Exception as e:
            logger.error(f"Failed to get running event loop: {e}")
            return []
    
    async def aget_messages(self) -> List[BaseMessage]:
        """
        async version of the messages property.
        Fetches up to window_size messages from the Redis list.
        "chat:{session_id}" deserializing from the stored JSON format.
        
        Returns
        -------
        A list of LangChain BaseMessage objects, ordered from oldest to newest
        or an empty list if no messages are found.
        """
        try:
            raw_messages = await self.redis.lrange(self._key, -self.window_size, -1)
        except Exception as e:
            logger.error(f"Failed to fetch messages from Redis for session {self.session_id}: {e}")
            return []
        
        if not raw_messages:
            return []
        
        messages: List[BaseMessage] = []
        for raw in raw_messages:
            try:
                msg_dict = json.loads(raw)
                messages.extend(messages_from_dict([msg_dict]))
            except Exception as e:
                logger.warning(
                    f"aget_messages: Failed to deserialize message from Redis for session {self.session_id}: {e}"
                )
        
        logger.debug(f"aget_messages: Retrieved {len(messages)} messages from Redis for session {self.session_id}")
        return messages
    
    def add_message(self, message: BaseMessage) -> None:
        """
        Synchronous interface required by BaseChatMessageHistory.
 
        Appends one message to the Redis list. Prefer aadd_message()
        in async call sites.
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self.aadd_message(message))
                    future.result()
            else:
                loop.run_until_complete(self.aadd_message(message))
        except Exception as exc:
            logger.error(
                f"RedisMessageHistory.add_message: failed for session={self.session_id}: {exc}"
            )
            
    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        """
        Synchronous bulk-add required by some LangChain runnables.
 
        Calls add_message for each message in order. Prefer
        aadd_messages() in async call sites.
        """
        for message in messages:
            self.add_message(message)
 
    async def aadd_message(self, message: BaseMessage) -> None:
        """
        Async: append one message to the Redis list, trim to window,
        and reset TTL.
 
        Steps (in order):
          1. Serialize the message to JSON via messages_to_dict().
          2. RPUSH to append to the right end of the list.
          3. LTRIM to keep only the newest window_size entries
             (trim from the left: LTRIM(key, -window_size, -1)).
          4. EXPIRE to reset the sliding TTL.
 
        Parameters
        ----------
        message   Any LangChain BaseMessage subclass.
        """
        try:
            msg_dict = messages_to_dict([message])[0]
            serialized = json.dumps(msg_dict)
        except Exception as exc:
            logger.error(
                f"aadd_message: serialization failed for session={self.session_id}: {exc}"
            )
            return
 
        try:
            await self.redis.rpush(self._key, serialized)
            await self.redis.ltrim(self._key, -self.window_size, -1)
            await self.redis.expire(self._key, self.ttl_seconds)
 
            logger.debug(
                f"aadd_message: appended {type(message).__name__} for session={self.session_id} "
                f"(window={self.window_size}, ttl={self.ttl_seconds}s)"
            )
        except Exception as exc:
            logger.error(
                f"aadd_message: Redis write failed for session={self.session_id}: {exc}"
            )
    
    async def aadd_messages(self, messages: Sequence[BaseMessage]) -> None:
        """
        Async bulk-add: appends multiple messages in a single pipeline.
 
        Uses a Redis pipeline to batch RPUSH, LTRIM, and EXPIRE into
        one round-trip, which is more efficient than calling aadd_message
        in a loop for large batches (e.g. loading a prior conversation
        into a fresh Redis key).
 
        Parameters
        ----------
        messages   Sequence of LangChain BaseMessage objects to append,
                   in the order they should be stored.
        """
        if not messages:
            return
 
        try:
            serialized_list = []
            for message in messages:
                msg_dict = messages_to_dict([message])[0]
                serialized_list.append(json.dumps(msg_dict))
        except Exception as exc:
            logger.error(
                f"aadd_messages: serialization failed for session={self.session_id}: {exc}"
            )
            return
 
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                for serialized in serialized_list:
                    pipe.rpush(self._key, serialized)
                pipe.ltrim(self._key, -self.window_size, -1)
                pipe.expire(self._key, self.ttl_seconds)
                await pipe.execute()
 
            logger.debug(
                f"aadd_messages: appended {len(messages)} message(s) in pipeline "
                f"for session={self.session_id}"
            )
        except Exception as exc:
            logger.error(
                f"aadd_messages: Redis pipeline failed for session={self.session_id}: {exc}"
            )
            
    def clear(self) -> None:
        """
        Synchronous interface required by BaseChatMessageHistory.
 
        Deletes the Redis key for this session's history. Prefer
        aclear() in async call sites.
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self.aclear())
                    future.result()
            else:
                loop.run_until_complete(self.aclear())
        except Exception as exc:
            logger.error(
                f"RedisMessageHistory.clear: failed for session={self.session_id}: {exc}"
            )
            
    async def aclear(self) -> None:
        """
        Async: delete the Redis history key for this session.
 
        Used on logout (DELETE /api/v1/auth/session/{session_id}) and
        by the session manager's cleanup routine. Does not raise if the
        key doesn't exist — DEL on a missing key is a no-op in Redis.
        """
        try:
            await self.redis.delete(self._key)
            logger.info(f"aclear: history deleted for session={self.session_id}")
        except Exception as exc:
            logger.error(
                f"aclear: Redis DEL failed for session={self.session_id}: {exc}"
            )
 
    async def alen(self) -> int:
        """
        Return the number of messages currently stored for this session.
 
        Useful for debugging and for the save_memory_node to decide
        whether to trigger a long-term archival summarization run.
 
        Returns
        -------
        The list length, or 0 if the key doesn't exist or the read fails.
        Never raises.
        """
        try:
            length = await self.redis.llen(self._key)
            return int(length)
        except Exception as exc:
            logger.error(f"alen: Redis LLEN failed for session={self.session_id}: {exc}")
            return 0
 
    def __repr__(self) -> str:
        return (
            f"RedisMessageHistory(session_id={self.session_id!r}, "
            f"window_size={self.window_size}, ttl_seconds={self.ttl_seconds})"
        )