from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from .config import Config

db = SQLAlchemy()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    db.init_app(app)

    from . import models
    from .routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        from .schema import upgrade_schema
        upgrade_schema()
        from .services import seed_data
        seed_data()

    from .hardware import HardwareController
    controller = HardwareController(app)
    app.extensions['hardware'] = controller
    if app.config.get('HARDWARE_AUTOSTART', True):
        controller.start()

    return app
