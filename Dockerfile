FROM python:3.12-slim

# ffmpeg/ffprobe são exigidos pela montagem do vídeo (pipeline/edicao.py)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Sem isto o Python bufferiza o stdout quando não há TTY, e no Render o log de
# uma execução inteira só aparece quando o processo morre — foi o que aconteceu
# na primeira execução real (2026-08-10): 13 minutos de log vazio e depois tudo
# de uma vez. Só o stderr chegava na hora, porque não é bufferizado, o que dava
# a impressão de que apenas os erros existiam. Acompanhar um cron de ~10 minutos
# em tempo real é a diferença entre ver a coleta afunilar e descobrir isso
# depois do fato.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# O Cron Job do Render sobrescreve isto pelo comando agendado.
# Padrão = Short do canal @NoCrazyWarPlease; "--long-take" gera a análise 16:9.
CMD ["python", "main.py"]
