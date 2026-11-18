"""Constants for the Assist voice bridge and router."""

DOMAIN = "assist_voice"
CONF_STT_ENTITY = "stt_entity"
CONF_BACKENDS = "backends"
CONF_SPEAKER_STT = "speaker_stt_entity"
CONF_RESPONSE_TIMEOUT = "stt_response_timeout"
DEFAULT_SPEAKER_STT = "stt.speaker_id_speech_to_text"
DEFAULT_RESPONSE_TIMEOUT = 30
GUARDED_STT_ENTITY = "stt.assist_voice_speaker_id"
CONF_LISTEN_HOST = "listen_host"
CONF_LISTEN_PORT = "listen_port"
DEFAULT_LISTEN_HOST = "0.0.0.0"
DEFAULT_LISTEN_PORT = 10352
SERVICE_ROTATE = "rotate"
