from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="RegistroAuditoria",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("registrado_em", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("usuario_nome", models.CharField(blank=True, max_length=150)),
                ("acao", models.CharField(choices=[("LOGIN", "Entrada no sistema"), ("LOGIN_FALHA", "Login recusado"), ("LOGOUT", "Saída do sistema"), ("CRIAR", "Cadastro criado"), ("ALTERAR", "Cadastro alterado"), ("EXCLUIR", "Cadastro excluído"), ("ATIVAR", "Acesso reativado"), ("DESATIVAR", "Acesso desativado"), ("PAPEL", "Papel alterado"), ("SENHA", "Senha alterada"), ("2FA", "Verificação em duas etapas"), ("CORRIGIR", "Dados pessoais corrigidos"), ("EXPORTAR", "Dados pessoais exportados")], max_length=12)),
                ("objeto_tipo", models.CharField(blank=True, max_length=60)),
                ("objeto_id", models.CharField(blank=True, max_length=40)),
                ("objeto_nome", models.CharField(blank=True, max_length=200)),
                ("detalhes", models.JSONField(blank=True, default=dict)),
                ("ip", models.GenericIPAddressField(blank=True, null=True)),
                ("usuario", models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "registro de auditoria",
                "verbose_name_plural": "registros de auditoria",
                "db_table": "registro_auditoria",
                "ordering": ["-registrado_em", "-id"],
                "indexes": [models.Index(fields=["acao", "registrado_em"], name="ix_audit_acao_data")],
            },
        ),
    ]
