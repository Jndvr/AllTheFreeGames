import os
from dotenv import load_dotenv

def load_environment():
    """
    Loads the primary config.env to get ENVIRONMENT,
    then loads the corresponding .env file.
    """
    # Load the primary config.env
    load_dotenv('config.env')
    env_type = os.getenv('ENVIRONMENT', 'development').lower()

    if env_type == 'production':
        dotenv_path = '.env.production'
    else:
        dotenv_path = '.env.development'

    # Load the environment-specific .env file
    load_dotenv(dotenv_path)
    print(f"Loaded environment variables from {dotenv_path}")
