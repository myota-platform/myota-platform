# Local and production operations

## Local

1. Start Colima with Kubernetes enabled: `make colima-start`.
2. Run dependency-free tests: `make test`.
3. For the browser slice: `make run`.
4. For PostGIS-backed containers: `make compose-up`.
5. For Kubernetes: `make k8s-install`, then `kubectl -n myota get pods` and `kubectl -n myota port-forward svc/myota-gateway 8080:8080`.

If Colima, kubectl or Helm is unavailable, `make test` and `make run` still work without external dependencies.

## Production notes

Use managed PostgreSQL where possible, enable PostGIS, store credentials in Kubernetes Secrets or an external secret manager, and back up core and geodata databases independently. Pin image digests, enforce network policies so services reach only their own database, and expose QGIS access only through a private network or bastion.

