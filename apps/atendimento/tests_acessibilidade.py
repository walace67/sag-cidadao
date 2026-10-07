"""
Estrutura de acessibilidade (eMAG) presente em todas as páginas.
A auditoria completa, com navegador, é o comando auditar_acessibilidade.
"""
from django.urls import reverse

from .tests import BaseSAG


class AcessibilidadeTest(BaseSAG):
    def test_atalhos_e_marcos_em_todas_as_paginas(self):
        self.client.force_login(self.u_ana)
        for url in [reverse("login"), reverse("atendimento:consulta"), reverse("atendimento:painel")]:
            if url != reverse("login"):
                self.client.force_login(self.u_ana)
            resp = self.client.get(url)
            for trecho in ('accesskey="1"', 'href="#conteudo"', 'id="conteudo"', 'id="menu"', 'id="rodape"',
                           'lang="pt-br"', 'id="alto-contraste"', 'aria-pressed="false"'):
                self.assertContains(resp, trecho, msg_prefix=url)

    def test_atalhos_seguem_o_padrao_emag(self):
        """eMAG: 1 conteúdo, 2 menu, 3 busca, 4 rodapé."""
        html = self.client.get(reverse("login")).content.decode()
        self.assertIn('href="#conteudo" accesskey="1"', html)
        self.assertIn('href="#menu" accesskey="2"', html)
        self.assertIn('href="#rodape" accesskey="4"', html)
        # Sem campo de busca na página, o atalho 3 leva à consulta de protocolo
        self.assertIn(f'href="{reverse("atendimento:consulta")}#busca" accesskey="3"', html)

    def test_atalho_de_busca_vai_ao_campo_da_propria_pagina(self):
        self.client.force_login(self.u_ana)
        for url in [reverse("atendimento:painel"), reverse("atendimento:consulta")]:
            resp = self.client.get(url)
            self.assertContains(resp, 'href="#busca" accesskey="3"', msg_prefix=url)
            self.assertContains(resp, 'id="busca"', msg_prefix=url)

    def test_primeiro_link_da_pagina_pula_para_o_conteudo(self):
        html = self.client.get(reverse("login")).content.decode()
        primeiro_link = html[html.index("<body"):].split("<a ", 1)[1]
        self.assertTrue(primeiro_link.startswith('href="#conteudo"'))

    def test_pagina_de_acessibilidade(self):
        resp = self.client.get(reverse("atendimento:acessibilidade"))
        self.assertContains(resp, "eMAG")
        self.assertContains(resp, "Atalhos de teclado")
