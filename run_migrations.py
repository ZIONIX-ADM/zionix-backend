import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

# asyncpg usa postgresql://, não postgresql+asyncpg://
DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")

MIGRATIONS = [
    "migrations/001_create_ativos.sql",
    "migrations/002_create_scores_historico.sql",
    "migrations/003_create_indices.sql",
    "migrations/004_create_scores_atual_view.sql",
]


async def main():
    print(f"Conectando em {DATABASE_URL[:50]}...")
    conn = await asyncpg.connect(DATABASE_URL, ssl="require")
    print("Conectado.\n")

    for path in MIGRATIONS:
        sql = Path(path).read_text()
        print(f"Rodando {path}...")
        try:
            await conn.execute(sql)
            print(f"  OK\n")
        except Exception as e:
            print(f"  ERRO: {e}\n")

    await conn.close()
    print("Migrations concluídas.")


asyncio.run(main())
