import asyncio
from app.db.base import get_session_factory
from sqlalchemy import text

async def check():
    async with get_session_factory()() as session:
        # Check tables
        result = await session.execute(text("SHOW TABLES"))
        tables = result.scalars().all()
        print("Tables found:", tables)
        # Count rows in key seed tables
        for table in ["departments", "doctors", "hospital_info", "medications"]:
            try:
                r = await session.execute(text(f"SELECT COUNT(*) FROM `{table}`"))
                count = r.scalar_one()
                print(f"  {table}: {count} rows")
            except Exception as e:
                print(f"  {table}: ERROR - {e}")

asyncio.run(check())