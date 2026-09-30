"""WSGI entry point and local development launcher."""

import os

from app import app

application = app


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('DENTAL_PORT', '5057')), debug=False)
