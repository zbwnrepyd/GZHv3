from flask import Blueprint

card_config_bp = Blueprint("card_config", __name__)
field_bp = Blueprint("field", __name__)
render_data_bp = Blueprint("render_data", __name__)
media_bp = Blueprint("media", __name__)
evidence_bp = Blueprint("evidence", __name__)

_registered = False


def register_routes(app):
    global _registered
    if _registered:
        return
    _registered = True

    from routes.card_config_routes import register as _r1
    from routes.field_routes import register as _r2
    from routes.render_routes import register as _r3
    from routes.media_routes import register as _r4
    from routes.evidence_routes import register as _r5
    _r1(card_config_bp)
    _r2(field_bp)
    _r3(render_data_bp)
    _r4(media_bp)
    _r5(evidence_bp)
    app.register_blueprint(card_config_bp, url_prefix="/api")
    app.register_blueprint(field_bp, url_prefix="/api")
    app.register_blueprint(render_data_bp, url_prefix="/api")
    app.register_blueprint(media_bp, url_prefix="/api")
    app.register_blueprint(evidence_bp, url_prefix="/api")
