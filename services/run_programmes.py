from http.server import ThreadingHTTPServer

from myota_logging import configure_logging
from programmes import ProgrammeHandler, seed

configure_logging("myota-programmes", component="api")

seed()
ThreadingHTTPServer(("0.0.0.0", 8002), ProgrammeHandler).serve_forever()
