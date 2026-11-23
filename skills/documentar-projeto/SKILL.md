---
name: documentar-projeto
description: Analisa a pasta de um projeto de software e gera documentação técnica, 100% local. Use quando a pessoa pede para analisar, documentar ou gerar a documentação de um projeto.
contextos: [projetos]
estado: ativa
privacidade: local
entradas: [texto, voz]
saidas: [texto, relatorio]
versao: 1
execucao: roteiro
gatilhos:
  - acao: consultar
    prioridade: 90
    parametros: {caminho: null}
    padrao:
      - '\b(?:escrev\w*|redij\w*|faca|fazer|cri\w*|ger\w*|atualiz\w*|prepar\w*)\b.{0,40}\bdocumentacao\b'
      - '\b(?:documentar|documente)\b'
---

# Documentar projeto

Usa a Skill ProjectAnalyzer (`services/project_analyzer/`): varredura, AST, grafo de dependências, ocultação de segredos e redação pelo modelo local.

## Regras

- Lê o projeto sem alterá-lo; escreve só na pasta de saída configurada.
- Nunca usa a nuvem.
- Sem caminho informado, pede o caminho da pasta.

Comandos com caminho ("analisar projeto E:\pasta") são reconhecidos por `detectar_comando_projeto`, antes dos gatilhos.
