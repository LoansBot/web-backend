from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from lblogging import Level
from lazy_integrations import LazyIntegrations as LazyItgs
import json
import secrets
import users.router
import logs.router


app = FastAPI(
    title='RedditLoans',
    description='See https://github.com/LoansBot'
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*']
)
app.include_router(users.router.router, prefix='/users')
app.include_router(logs.router.router, prefix='/logs')


@app.get('/')
def root():
    return {"message": "Hello World"}


@app.get('/test_log')
def test_log():
    with LazyItgs() as itgs:
        itgs.logger.print(Level.TRACE, 'test_log')
    return Response(status_code=status.HTTP_200_OK)


@app.get('/test_cache')
def test_cache():
    with LazyItgs() as itgs:
        resp = json.dumps({'message': 'how you doing'})
        itgs.cache.set('test', resp.encode('utf-8'))
        return json.loads(itgs.cache.get('test').decode('utf-8'))


@app.get('/test_amqp')
def test_amqp():
    with LazyItgs() as itgs:
        itgs.channel.queue_declare(queue='hello')

        pub_body = secrets.token_urlsafe(16)
        itgs.channel.basic_publish(
            exchange='',
            routing_key='hello',
            body=pub_body.encode('utf-8'),
            mandatory=True
        )
        for mf, props, body_bytes in itgs.channel.consume('hello', inactivity_timeout=1):
            if mf is None:
                itgs.logger.print(Level.WARN, 'test_amqp reached inactivity timeout')
                itgs.channel.cancel()
                return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
            itgs.channel.basic_ack(mf.delivery_tag)
            con_body = body_bytes.decode('utf-8')
            if con_body != pub_body:
                itgs.logger.print(
                    Level.WARN,
                    'test_amqp expected response {} but got {}',
                    pub_body, con_body
                )
                continue
            itgs.channel.cancel()
            return Response(status_code=status.HTTP_200_OK)
