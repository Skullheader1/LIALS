import os

import logging
import configparser

from waitress import serve

from utils.logger import logger

from web.flask_server import app, initialise
from database import db

if __name__ == "__main__":
    logger.log(msg="Starting up...", level=logging.INFO)

    # Read configuration and initialise storage
    config = configparser.ConfigParser()
    config.read('config.ini')

    database_uri = os.environ.get('DATABASE_URI', config.get('database', 'database_uri', fallback='sqlite:///database.db'))

    if database_uri.startswith('sqlite:///') and not database_uri.startswith('sqlite:////'):
        relative_path = database_uri[len('sqlite:///'):]
        absolute_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)
        database_uri = f'sqlite:///{absolute_path}'

    app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        initialise()

    logger.log(msg="Initialised", level=logging.INFO)
    logger.log(msg="Starting web server...", level=logging.INFO)

    host = os.environ.get('HOST', config.get('server', 'host', fallback='0.0.0.0'))
    port = os.environ.get('PORT', config.getint('server', 'port', fallback=5050))

    serve(app, host=host, port=port, threads=4)
