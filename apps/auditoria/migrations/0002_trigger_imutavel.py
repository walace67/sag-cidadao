"""
Migração escrita à mão: o makemigrations não gera triggers.

Um TRIGGER é uma função que o próprio banco executa antes (BEFORE) ou
depois (AFTER) de um INSERT, UPDATE ou DELETE. Este recusa qualquer
UPDATE ou DELETE na trilha de auditoria, venha da aplicação, de um
script ou de alguém digitando no psql.

Só vale no PostgreSQL (no SQLite a migração não faz nada).
"""
from django.db import migrations

CRIAR = [
    """
    CREATE OR REPLACE FUNCTION registro_auditoria_imutavel() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION USING MESSAGE =
            'A trilha de auditoria não pode ser alterada nem apagada (' || TG_OP || ').';
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER registro_auditoria_imutavel
        BEFORE UPDATE OR DELETE ON registro_auditoria
        FOR EACH ROW EXECUTE FUNCTION registro_auditoria_imutavel()
    """,
]

DESFAZER = [
    "DROP TRIGGER IF EXISTS registro_auditoria_imutavel ON registro_auditoria",
    "DROP FUNCTION IF EXISTS registro_auditoria_imutavel()",
]


def criar(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for comando in CRIAR:
            schema_editor.execute(comando, params=None)


def desfazer(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for comando in DESFAZER:
            schema_editor.execute(comando, params=None)


class Migration(migrations.Migration):
    dependencies = [("auditoria", "0001_initial")]
    operations = [migrations.RunPython(criar, desfazer)]
