from fastapi import FastAPI, Response, status
from lblogging import Level
from constants import LOGGER, MEMCACHED as cache, AMQP_CHANNEL as channel
import json
import secrets


app = FastAPI()  # noqa
logger = LOGGER.with_iden('main.py')  # noqa


@app.get('/')
def root():
    return {"message": "Hello World"}


@app.get('/test_log')
def test_log():
    logger.print(Level.TRACE, 'test_log')
    logger.connection.commit()
    return Response(status_code=status.HTTP_200_OK)


@app.get('/test_cache')
def test_cache():
    resp = json.dumps({'message': 'how you doing'})
    cache.set('test', resp.encode('utf-8'))
    return json.loads(cache.get('test').decode('utf-8'))


@app.get('/test_amqp')
def test_amqp():
    channel.queue_declare(queue='hello')
    pub_body = secrets.token_urlsafe(16)
    channel.basic_publish(
        exchange='',
        routing_key='hello',
        body=pub_body.encode('utf-8'),
        mandatory=True
    )
    for method_frame, properties, body_bytes in channel.consume('hello', inactivity_timeout=1):
        if method_frame is None:
            logger.print(Level.WARN, 'test_amqp reached inactivity timeout')
            logger.connection.commit()
            return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        channel.basic_ack(method_frame.delivery_tag)
        con_body = body_bytes.decode('utf-8')
        if con_body != pub_body:
            logger.print(
                Level.WARN,
                'test_amqp expected response {} but got {}',
                pub_body, con_body
            )
            logger.connection.commit()
    return Response(status_code=status.HTTP_200_OK)
