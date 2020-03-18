from fastapi import FastAPI, Response, status
from lblogging import Level
import integrations as itgs
import json
import secrets
import users.router
from flask_cors import CORS


app = FastAPI(
    title='RedditLoans',
    description='See https://github.com/LoansBot'
)
CORS(app)
app.include_router(users.router.router, prefix='/users')


@app.get('/')
def root():
    return {"message": "Hello World"}


@app.get('/test_log')
def test_log():
    with itgs.logger('main.py') as logger:
        logger.print(Level.TRACE, 'test_log')
    return Response(status_code=status.HTTP_200_OK)


@app.get('/test_cache')
def test_cache():
    with itgs.memcached() as cache:
        resp = json.dumps({'message': 'how you doing'})
        cache.set('test', resp.encode('utf-8'))
        return json.loads(cache.get('test').decode('utf-8'))


@app.get('/test_amqp')
def test_amqp():
    with itgs.amqp() as (amqp, channel), itgs.logger('main.py') as logger:
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
                channel.cancel()
                return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
            channel.basic_ack(method_frame.delivery_tag)
            con_body = body_bytes.decode('utf-8')
            if con_body != pub_body:
                logger.print(
                    Level.WARN,
                    'test_amqp expected response {} but got {}',
                    pub_body, con_body
                )
                continue
            channel.cancel()
            return Response(status_code=status.HTTP_200_OK)
