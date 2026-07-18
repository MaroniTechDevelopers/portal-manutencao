"""
Conector para API do Arquivei.
Documentação: https://app.arquivei.com.br/developers
Autenticação: OAuth 2.0 (client_credentials)
"""
import os

class ArquiveiConnector:
    BASE_URL = "https://app.arquivei.com.br/api/v1"

    def __init__(self):
        self.client_id     = os.environ.get("ARQUIVEI_CLIENT_ID", "")
        self.client_secret = os.environ.get("ARQUIVEI_CLIENT_SECRET", "")
        self.token         = None

    def autenticar(self):
        """Obtém token OAuth 2.0. Implementar quando API estiver disponível."""
        raise NotImplementedError("Configurar ARQUIVEI_CLIENT_ID e ARQUIVEI_CLIENT_SECRET")

    def listar_nfe(self, data_inicio, data_fim, pagina=1):
        """
        Lista NF-e emitidas no período.
        Retorna lista de dicts compatíveis com o schema de base.json.
        Campos esperados: chave, ufOrig, ufDest, cnpjDest, cnpjEmit,
                          fornecedor, data, numero, valor, statusArq, item, produto
        """
        raise NotImplementedError("Implementar após confirmar endpoints com Arquivei")

    def is_configurado(self):
        return bool(self.client_id and self.client_secret)
