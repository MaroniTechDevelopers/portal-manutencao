"""
Conector para API do Rodopar (TMS).
ATENÇÃO: Confirmar disponibilidade de API com suporte Rodopar antes de implementar.
Contato suporte: verificar com equipe de TI do Grupo Trans Maroni.
"""
import os

class RodoparConnector:

    def __init__(self):
        self.api_key  = os.environ.get("RODOPAR_API_KEY", "")
        self.base_url = os.environ.get("RODOPAR_BASE_URL", "")

    def atualizar_status_nf(self, chave_acesso, status):
        """
        Atualiza status de contabilização de uma NF no Rodopar.
        chave_acesso: string de 44 dígitos
        status: 'Contabilizado' | 'Pendente'
        """
        raise NotImplementedError("Aguardando documentação de API do Rodopar")

    def is_configurado(self):
        return bool(self.api_key and self.base_url)
