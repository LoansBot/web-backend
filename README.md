# Web Backend

This repository has the web backend which runs on FastAPI. The protocol is
json-based and REST-inspired.

## Environment Variables

- APPNAME: The name to identify with when logging
- ROOT_DOMAIN: The url we treat as our root, typically https://redditloans.com
  (note the lack of trailing slash).
- PGHOST: Database host
- PGPORT: Database port
- PGDATABASE: Database name
- PGUSER: Username for the database
- PGPASSWORD: Password for the database
- AMQP_HOST: Host for the AMQP
- AMQP_PORT: Port for the AMQP
- AMQP_USERNAME: Username for AMQP
- AMQP_PASSWORD: Password for AMQP
- AMQP_REDDIT_PROXY_QUEUE: The reddit proxy's queue
- AMQP_RESPONSE_QUEUE: The queue to use for responses. Make sure that this
  is unique to each process.
- AMQP_VHOST: The virtual host for the AMQP
- MEMCACHED_HOST: The host for the memcached
- MEMCACHED_PORT: The port for the memcached server
- WEBHOST: The host to bind on
- WEBPORT: The port to bind on
- UVICORN_PATH: The path to the uvicorn executable
