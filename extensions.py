"""
DeadCodeX Flask Extensions
Centralized extension initialization for clean app factory pattern
"""
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_migrate import Migrate

# Initialize extensions (no app bound yet)
db = SQLAlchemy()
jwt = JWTManager()
cors = CORS()
migrate = Migrate()
