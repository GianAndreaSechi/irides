from pydantic import BaseModel

class ConnectionRequest(BaseModel):
    config_name: str
