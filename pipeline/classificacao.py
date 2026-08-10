"""Classificação das trends candidatas: macrotema + imagem mental.

Este módulo era o filtro de "acessibilidade pré-conceitual" (score 1-5; só
virava vídeo candidata com score >= 4). Diretriz de 2026-07-18: a seleção
passou a ser guiada SOMENTE pelo que a audiência do canal está assistindo —
sem pesos nem filtro editorial, nenhuma candidata é rejeitada aqui. O que
sobrou desta etapa é a anotação que a seleção ainda precisa:

- macrotema: rotula a candidata para a seleção poder ler a régua de audiência
  por TEMA e não vídeo a vídeo ("os 'guerra-conflito' fazem 15 mil views, os
  'diplomacia-tratados' fazem 200" — ver escritor.py). É também o que alimenta
  o rodízio de temas dos Shorts;
- imagem_mental: o que a pessoa visualiza ao ouvir a notícia; é a matéria-prima
  do HOOK na hora do roteiro.

Uma única chamada ao GPT anota todas as candidatas, e todas seguem vivas para
a seleção.
"""

import json

from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, Config

# Macrotemas do canal, todos DENTRO da geopolítica — o canal não cobre outra
# coisa, então o macrotema não separa "geopolítica de o resto": ele separa os
# RECORTES da geopolítica entre si. É isso que faz o rodízio funcionar. No
# formato CURTO eles têm efeito de regra: o RODÍZIO de temas dos Shorts
# (escritor.py) veta as candidatas cujo macrotema é o do Short anterior, para
# que dois Shorts seguidos não sejam a mesma frente da mesma guerra. No formato
# longo eles seguem só como contexto.
#
# A granularidade é de propósito maior do que num canal generalista: com dois
# ou três rótulos ("guerra", "diplomacia"), um ciclo quente de conflito
# ocuparia o canal inteiro e o rodízio não teria para onde ir.
MACROTEMAS = [
    "guerra-conflito",
    "defesa-armamento",
    "nuclear-estrategico",
    "inteligencia-espionagem",
    "diplomacia-tratados",
    "sancoes-comercio",
    "energia-recursos",
    "poder-interno",
    "fronteiras-migracao",
    "americas",
    "outro",
]

MACROTEMAS_DESCRICAO = """\
- guerra-conflito: combate em curso — ofensiva, ataque, bombardeio, avanço ou
  recuo de linha, cessar-fogo, baixas, ocupação de território
- defesa-armamento: armas e capacidade militar fora do combate — sistema novo,
  entrega ou venda de equipamento, contrato de defesa, orçamento militar,
  exercício, mobilização, base
- nuclear-estrategico: programa nuclear, míssil de longo alcance, teste,
  arsenal, tratado de armas estratégicas, inspeção da AIEA
- inteligencia-espionagem: espionagem, vazamento de documento, sabotagem,
  ciberataque atribuído a Estado, operação encoberta, prisão de agente
- diplomacia-tratados: negociação, cúpula, aliança, adesão, acordo, rompimento
  de relações, voto em organismo multilateral, reconhecimento de Estado
- sancoes-comercio: sanção, embargo, tarifa, controle de exportação, congelamento
  de ativo, guerra comercial, disputa por cadeia de suprimento
- energia-recursos: petróleo, gás, rota marítima, mineral crítico, água,
  alimento — a disputa pelo recurso e o preço que sai dela
- poder-interno: mudança de poder dentro de um país com efeito lá fora —
  eleição, golpe, protesto de massa, repressão, colapso de governo
- fronteiras-migracao: disputa territorial, fronteira, refugiado, deslocamento
  em massa, crise migratória
- americas: o hemisfério visto de perto — Venezuela, Brasil no mundo, América
  Latina, e a relação dela com Estados Unidos e China. Se o fato é de outra
  região, use o macrotema do assunto, não este
- outro: geopolítica que não couber acima\
"""

INSTRUCOES_CLASSIFICACAO = """\
Você anota notícias candidatas a vídeo de um canal de análise de GEOPOLÍTICA.

Para CADA notícia, preencha:
- "macrotema": UM macrotema da lista:
{macrotemas}
- "imagem_mental": descrição em 5 palavras do que a pessoa VISUALIZA ao ouvir
  a notícia; deixe vazio se ela não evocar nenhuma cena concreta.

Anote TODAS as notícias listadas, na mesma ordem, usando o campo "indice".
Responda somente com o JSON pedido.\
""".format(macrotemas=MACROTEMAS_DESCRICAO)

ESQUEMA_CLASSIFICACAO = {
    "name": "classificacao_trends",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "avaliacoes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "indice": {
                            "type": "integer",
                            "description": "Número da notícia na lista recebida.",
                        },
                        "imagem_mental": {
                            "type": "string",
                            "description": (
                                "Descrição em 5 palavras do que a pessoa "
                                "visualiza; vazio se não houver imagem mental."
                            ),
                        },
                        "macrotema": {
                            "type": "string",
                            "enum": MACROTEMAS,
                            "description": (
                                "Macrotema da notícia, conforme a lista das "
                                "instruções."
                            ),
                        },
                    },
                    "required": ["indice", "imagem_mental", "macrotema"],
                },
            }
        },
        "required": ["avaliacoes"],
    },
}


def _listar_candidatas(trends: list[dict]) -> str:
    linhas = []
    for i, t in enumerate(trends, 1):
        linhas.append(f"{i}. {t['trend']}\n   Resumo: {t['resumo']}")
    return "\n".join(linhas)


def classificar_trends(cfg: Config, trends: list[dict]) -> list[dict]:
    """Anota cada trend com macrotema e imagem_mental (1 chamada, sem filtro).

    Falha na chamada ABORTA a execução: sem o macrotema não existe o teto de
    repetição de macrotemas, e rodar sem ele é o que deixa o canal virar
    monotemático sem ninguém perceber.
    """
    cliente = OpenAI(api_key=cfg.openai_api_key)

    print(f"[classificacao] Classificando {len(trends)} candidatas "
          "(macrotema + imagem mental)...")
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES_CLASSIFICACAO},
                {
                    "role": "user",
                    "content": AVISO_DADOS_EXTERNOS
                    + "\n\nNotícias candidatas:\n"
                    + _listar_candidatas(trends),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ESQUEMA_CLASSIFICACAO,
            },
        )
        avaliacoes = json.loads(resposta.choices[0].message.content)["avaliacoes"]
    except Exception as erro:  # noqa: BLE001 — sem macrotema não há teto de repetição
        raise SystemExit(
            "Classificação das candidatas falhou (OpenAI) — sem macrotema não "
            f"existe o teto de repetição de macrotemas; abortando: {erro}"
        ) from erro

    por_indice = {a["indice"]: a for a in avaliacoes}
    anotadas = []
    for i, trend in enumerate(trends, 1):
        av = por_indice.get(i, {})
        imagem = (av.get("imagem_mental") or "").strip()
        macrotema = (av.get("macrotema") or "").strip().lower()
        if macrotema not in MACROTEMAS:
            macrotema = "outro"
        print(
            f"[classificacao] [{macrotema}] — {trend['trend']}\n"
            f"                imagem mental: {imagem or '(nenhuma)'}"
        )
        anotadas.append(dict(trend, imagem_mental=imagem, macrotema=macrotema))
    return anotadas
