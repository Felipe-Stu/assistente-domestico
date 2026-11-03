"""
Índice incremental (cache por hash) e histórico de evolução do projeto.

O índice fica na pasta de saída da documentação, nunca no projeto analisado.
Arquivos com hash inalterado reutilizam os fatos e o resumo do LLM já calculados.
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

VERSAO_INDICE = 1


class IndiceIncremental:
    def __init__(self, caminho_indice: str, caminho_historico: str):
        self.caminho_indice = caminho_indice
        self.caminho_historico = caminho_historico
        self.anterior: Dict[str, Any] = self._carregar(caminho_indice, {"versao": VERSAO_INDICE, "raiz": None, "arquivos": {}})
        if self.anterior.get("versao") != VERSAO_INDICE:
            self.anterior = {"versao": VERSAO_INDICE, "raiz": None, "arquivos": {}}
        self.atual: Dict[str, Any] = {"versao": VERSAO_INDICE, "raiz": None, "arquivos": {}, "arquitetura": None}

    @staticmethod
    def _carregar(caminho: str, padrao: Any) -> Any:
        if not os.path.exists(caminho):
            return padrao
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return padrao

    # ------------------------------------------------------------------
    def entrada_anterior(self, caminho: str, sha256: str) -> Optional[Dict[str, Any]]:
        """Retorna a entrada do índice anterior se o arquivo não mudou."""
        entrada = self.anterior.get("arquivos", {}).get(caminho)
        if entrada and entrada.get("sha256") == sha256:
            return entrada
        return None

    def registrar(self, caminho: str, sha256: str, fatos: Optional[Dict[str, Any]], resumo: Optional[Dict[str, Any]] = None) -> None:
        self.atual["arquivos"][caminho] = {"sha256": sha256, "fatos": fatos, "resumo": resumo}

    def definir_resumo(self, caminho: str, resumo: Optional[Dict[str, Any]]) -> None:
        if caminho in self.atual["arquivos"]:
            self.atual["arquivos"][caminho]["resumo"] = resumo

    def arquitetura_anterior(self) -> Optional[Dict[str, Any]]:
        return self.anterior.get("arquitetura")

    # ------------------------------------------------------------------
    def calcular_alteracoes(self) -> Dict[str, Any]:
        antes = self.anterior.get("arquivos", {})
        depois = self.atual["arquivos"]
        adicionados = sorted(set(depois) - set(antes))
        removidos = sorted(set(antes) - set(depois))
        modificados = sorted(c for c in set(antes) & set(depois) if antes[c].get("sha256") != depois[c].get("sha256"))

        def simbolos(entrada: Optional[Dict[str, Any]]) -> set:
            fatos = (entrada or {}).get("fatos") or {}
            nomes = {f"função {f['nome']}" for f in fatos.get("funcoes", [])}
            for c in fatos.get("classes", []):
                nomes.add(f"classe {c['nome']}")
                nomes.update(f"método {c['nome']}.{m}" for m in c.get("metodos", []))
            return nomes

        detalhes = {}
        for c in modificados:
            novos = sorted(simbolos(depois[c]) - simbolos(antes[c]))
            retirados = sorted(simbolos(antes[c]) - simbolos(depois[c]))
            if novos or retirados:
                detalhes[c] = {"adicionados": novos, "removidos": retirados}

        return {
            "primeira_analise": not antes,
            "adicionados": adicionados,
            "removidos": removidos,
            "modificados": modificados,
            "simbolos": detalhes,
        }

    # ------------------------------------------------------------------
    def salvar(self, raiz: str, arquitetura: Optional[Dict[str, Any]], alteracoes: Dict[str, Any],
               estatisticas: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Grava o índice e acrescenta uma entrada ao histórico. Retorna o histórico completo."""
        self.atual["raiz"] = raiz
        self.atual["arquitetura"] = arquitetura
        self.atual["gerado_em"] = datetime.now().isoformat(timespec="seconds")
        os.makedirs(os.path.dirname(self.caminho_indice), exist_ok=True)
        with open(self.caminho_indice, "w", encoding="utf-8") as f:
            json.dump(self.atual, f, ensure_ascii=False)

        historico = self._carregar(self.caminho_historico, [])
        if not isinstance(historico, list):
            historico = []
        houve_mudanca = alteracoes["primeira_analise"] or any(alteracoes[k] for k in ("adicionados", "removidos", "modificados"))
        if houve_mudanca:
            historico.append({
                "data": self.atual["gerado_em"],
                "estatisticas": estatisticas,
                "adicionados": alteracoes["adicionados"],
                "removidos": alteracoes["removidos"],
                "modificados": alteracoes["modificados"],
                "simbolos": alteracoes["simbolos"],
                "primeira_analise": alteracoes["primeira_analise"],
            })
            with open(self.caminho_historico, "w", encoding="utf-8") as f:
                json.dump(historico, f, ensure_ascii=False, indent=1)
        return historico
