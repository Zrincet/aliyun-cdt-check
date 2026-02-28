FROM python:3.11-alpine

WORKDIR /app

COPY ./app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app

RUN apk add --no-cache tzdata && \
    cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone && \
    apk del tzdata

RUN echo "*/30 * * * * python3 /app/aliyun_cdt_check.py > /dev/null 2>&1" > /etc/crontabs/root && \
    echo "1 8 * * * python3 /app/dailyjob.py > /dev/null 2>&1" >> /etc/crontabs/root

CMD ["crond", "-f"]
