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
- HCAPTCHA_SECRET: The hcaptcha secret; not required. If specified, the
  earnings from hCaptcha will be sent here.
- ARANGO_AUTH: See https://github.com/Tjstretchalot/arango_crud/blob/master/src/arango_crud/env_config.py#L87
- ARANGO_AUTH_CACHE: See https://github.com/Tjstretchalot/arango_crud/blob/master/src/arango_crud/env_config.py#L109
- ARANGO_AUTH_USERNAME: See https://github.com/Tjstretchalot/arango_crud/blob/master/src/arango_crud/env_config.py#L90
- ARANGO_AUTH_PASSWORD: See https://github.com/Tjstretchalot/arango_crud/blob/master/src/arango_crud/env_config.py#L91
- ARANGO_TTL_SECONDS: See https://github.com/Tjstretchalot/arango_crud/blob/master/src/arango_crud/env_config.py#L74
- ARANGO_DB: The arango database to connect to
