from http.server import ThreadingHTTPServer
from programmes import ProgrammeHandler, seed

seed()
ThreadingHTTPServer(("0.0.0.0", 8002), ProgrammeHandler).serve_forever()

