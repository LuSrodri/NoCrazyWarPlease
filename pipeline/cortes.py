"""Planejamento dos cortes: a IA decide quando cada clipe entra e quanto fica.

O modelo recebe a narração e os clipes de vídeo disponíveis (os aprovados pela
auditoria, todos dos posts do X da trend, com as descrições do GPT com visão
sobre os arquivos baixados) e devolve a sequência de cortes. A regra 5 abaixo
ainda manda omitir clipe fora do assunto, mas ela virou rede de segurança: o
descarte de material impróprio é responsabilidade da auditoria (auditoria.py),
que roda antes e não devolve o clipe reprovado ao fallback. Cada corte é
ancorado numa
CITAÇÃO EXATA do texto da narração — nunca em segundos, que LLM chuta — e a
citação é convertida em tempo real pelos timestamps por caractere do
alinhamento do ElevenLabs (já remapeados após o corte de silêncios).

Qualquer falha (resposta inválida, citações não encontradas, poucos cortes)
devolve None e o main.py cai no posicionamento automático de sempre.
"""

import json
from pathlib import Path

from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, Config

# Mínimo de cortes válidos para aceitar o plano (abaixo disso, fallback). Com
# até 3 clipes, ficar num único clipe forte o vídeo inteiro é escolha
# editorial legítima — só o plano VAZIO (resposta inútil) cai no fallback.
MIN_CORTES = 1

ESQUEMA_CORTES = {
    "name": "plano_de_cortes",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cortes": {
                "type": "array",
                "description": (
                    "A sequência de cortes do vídeo, em ordem cronológica da "
                    "narração."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "midia": {
                            "type": "string",
                            "description": "id da mídia escolhida (ex.: m3)",
                        },
                        "entra_em": {
                            "type": "string",
                            "description": (
                                "citação EXATA e curta (3 a 8 palavras "
                                "consecutivas) do texto da narração, copiada "
                                "caractere por caractere, marcando onde a "
                                "mídia entra"
                            ),
                        },
                    },
                    "required": ["midia", "entra_em"],
                },
            },
        },
        "required": ["cortes"],
    },
}

INSTRUCOES_CORTES = """\
Você é o EDITOR DE CORTES de um vídeo vertical curto (YouTube Shorts) narrado.

Você recebe o texto da NARRAÇÃO (com duração total) e os CLIPES DE VÍDEO
disponíveis (até 3, todos anexados aos posts originais do X sobre o fato),
cada um com um id, a duração e a descrição do que mostra. O vídeo é montado
SOMENTE com esses clipes — não há fotos.

Monte a sequência de cortes: qual clipe aparece, em que ordem e em que momento
da narração cada um ENTRA. Cada clipe fica na tela até o próximo entrar (o
último vai até o fim; clipe mais curto que a janela repete em loop). Regras:

1. "entra_em" é uma citação EXATA e CURTA (3 a 8 palavras consecutivas) do
   texto da narração, copiada caractere por caractere, com a mesma pontuação e
   acentuação. NÃO parafraseie: a citação é localizada no texto por busca
   literal, e citação que não existir descarta o corte.
2. O primeiro corte DEVE citar as primeiras palavras da narração — o vídeo
   nunca começa sem clipe na tela. O primeiro clipe decide o "viewed vs
   swiped": abra com o clipe mais forte que couber no gancho.
3. CASE clipe e fala: o clipe entra quando a narração fala do que ele mostra.
   Com poucos clipes, divida a narração em blocos que façam sentido com o
   conteúdo de cada um — o momento da troca importa mais que a quantidade.
4. RITMO (estime ~2,5 palavras por segundo): nenhum clipe fica menos de ~3s na
   tela, e as janelas NÃO precisam ser iguais — clipe forte segura 8 a 15s,
   clipe de apoio resolve em 3 a 6s. Se possível, troque de clipe perto da
   virada da narração (fato → implicação) para renovar a atenção.
5. Clipe fora do assunto, redundante ou que só mostra logomarca: NÃO use
   (basta omitir — com 1 clipe bom o vídeo inteiro pode ficar nele). Não
   repita clipe.

Responda somente com o JSON pedido.\
"""

INSTRUCOES_CORTES_LONGO = """\
Você é o EDITOR DE CORTES de um vídeo de ANÁLISE em 16:9, de cerca de
{duracao} segundos, narrado e SEM legendas na tela.

Você recebe o texto da NARRAÇÃO (com duração total) e os CLIPES DE VÍDEO
disponíveis (até {max_clipes}, todos anexados aos posts originais do X sobre o
fato), cada um com um id, a duração e a descrição do que mostra. O vídeo é
montado SOMENTE com esses clipes — não há fotos nem imagens de banco.

Monte a sequência de cortes: qual clipe aparece, em que ordem e em que momento
da narração cada um ENTRA. Cada clipe fica na tela até o próximo entrar (o
último vai até o fim; clipe mais curto que a janela repete em loop). Regras:

1. "entra_em" é uma citação EXATA e CURTA (3 a 8 palavras consecutivas) do
   texto da narração, copiada caractere por caractere, com a mesma pontuação e
   acentuação. NÃO parafraseie: a citação é localizada por busca literal, e
   citação que não existir descarta o corte.
2. O primeiro corte DEVE citar as primeiras palavras da narração — o vídeo
   nunca começa sem clipe na tela. Abra com o clipe mais forte que couber no
   gancho.
3. USE TODOS OS CLIPES QUE PRESTAREM: dois minutos parados no mesmo clipe
   cansam. Mire em trocar a cada 8 a 20 segundos e distribua os cortes ao
   longo de toda a narração — o vídeo não pode ter todos os cortes no começo e
   um clipe único segurando a segunda metade.
4. CASE clipe e fala: o clipe entra quando a narração fala do que ele mostra.
   Troque de clipe nas viradas de assunto da narração (o fato → o terreno →
   os interesses → o dinheiro → o precedente): a troca marca o novo bloco e
   renova a atenção.
5. Clipe fora do assunto, redundante ou que só mostra logomarca: NÃO use
   (basta omitir). Não repita clipe.

Responda somente com o JSON pedido.\
"""


def _rotulo(m: dict) -> str:
    """Linha de apresentação de um clipe para o modelo."""
    if m.get("dur_s"):
        tipo = f"CLIPE DE VÍDEO de {m['dur_s']:.0f}s"
    else:
        tipo = "CLIPE DE VÍDEO"
    conta = f", post de {m['conta']}" if m.get("conta") else ""
    return f"[{tipo}{conta}] {m.get('descricao', '').strip()}"


def _tempo_do_char(alinhamento: dict, texto: str, pos: int, dur_total: float) -> float:
    """Instante (s) em que o caractere `pos` do texto é falado.

    Usa os timestamps por caractere do ElevenLabs quando eles casam com o
    texto; senão, aproxima pela fração de caracteres (comportamento antigo).
    """
    chars = alinhamento.get("characters") or []
    inicios = alinhamento.get("character_start_times_seconds") or []
    if (
        chars
        and len(chars) == len(inicios)
        and "".join(chars) == texto
        and 0 <= pos < len(inicios)
    ):
        return float(inicios[pos])
    return pos / max(len(texto), 1) * dur_total


def planejar_cortes(
    cfg: Config,
    texto_video: str,
    midias: list[dict],
    alinhamento: dict,
    dur_total: float,
) -> list[dict] | None:
    """Planeja os cortes; devolve sobreposições com tempo explícito ou None.

    `midias`: [{"caminho": Path, "tipo": str, "descricao": str,
    "dur_s": float|None, "conta": str}, ...]. O retorno é compatível com
    `montar_video`: [{"caminho", "inicio_s", "inicio_frac", "fim_frac"}, ...].
    """
    if not midias:
        return None

    listagem = "\n".join(
        f"m{k}: {_rotulo(m)}" for k, m in enumerate(midias, 1)
    )
    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"NARRAÇÃO ({dur_total:.0f}s, {len(texto_video.split())} palavras):\n"
        f"{texto_video}\n\n"
        f"MÍDIAS DISPONÍVEIS:\n{listagem}"
    )

    instrucoes = (
        INSTRUCOES_CORTES_LONGO.format(
            duracao=round(dur_total), max_clipes=cfg.max_clipes
        )
        if cfg.formato == "longo"
        else INSTRUCOES_CORTES
    )

    cliente = OpenAI(api_key=cfg.openai_api_key)
    print(f"[cortes] Planejando os cortes de {len(midias)} mídias...")
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": instrucoes},
                {"role": "user", "content": conteudo},
            ],
            response_format={"type": "json_schema", "json_schema": ESQUEMA_CORTES},
        )
        cortes = json.loads(resposta.choices[0].message.content)["cortes"]
    except Exception as erro:
        print(f"[aviso] Planejador de cortes falhou ({erro}); posicionamento automático")
        return None

    texto_baixo = texto_video.lower()
    plano: list[dict] = []
    usadas: set[int] = set()
    # Os cortes vêm em ordem cronológica; a busca avança um cursor para que
    # uma citação repetida no texto case com a ocorrência DEPOIS do corte
    # anterior, não sempre com a primeira.
    cursor = 0
    for corte in cortes:
        id_bruto = str(corte.get("midia", "")).strip().lstrip("m")
        try:
            indice = int(id_bruto) - 1
        except ValueError:
            continue
        if not 0 <= indice < len(midias) or indice in usadas:
            continue
        citacao = str(corte.get("entra_em", "")).strip().lower()
        pos = texto_baixo.find(citacao, cursor) if citacao else -1
        if pos < 0 and citacao:
            pos = texto_baixo.find(citacao)
        if pos < 0:
            print(f"[cortes] citação não encontrada, corte ignorado: \"{citacao}\"")
            continue
        cursor = pos + 1
        usadas.add(indice)
        inicio = _tempo_do_char(alinhamento, texto_video, pos, dur_total)
        plano.append(
            {
                "caminho": midias[indice]["caminho"],
                "inicio_s": min(max(0.0, inicio), dur_total),
                "inicio_frac": min(max(0.0, inicio), dur_total) / max(dur_total, 0.01),
                "fim_frac": None,
            }
        )

    if len(plano) < min(MIN_CORTES, len(midias)):
        print(
            f"[aviso] Plano de cortes com só {len(plano)} corte(s) válido(s); "
            "posicionamento automático"
        )
        return None

    plano.sort(key=lambda p: p["inicio_s"])
    plano[0]["inicio_s"] = 0.0
    plano[0]["inicio_frac"] = 0.0
    resumo = ", ".join(
        f"{Path(p['caminho']).name}@{p['inicio_s']:.1f}s" for p in plano
    )
    print(f"[cortes] {len(plano)} cortes: {resumo}")
    return plano
