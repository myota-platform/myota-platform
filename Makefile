.PHONY: test run compose-up colima-start k8s-install

test:
	python3 -m unittest discover -s tests -v

run:
	MYOTA_REQUIRE_DURABILITY=1 \
	CORE_DATABASE_URL=$${CORE_DATABASE_URL:-postgresql://myota:myota-dev-only@127.0.0.1:5432/myota_core} \
	GEO_DATABASE_URL=$${GEO_DATABASE_URL:-postgresql://myota:myota-dev-only@127.0.0.1:5432/myota_geo} \
	python3 services/dev_server.py

colima-start:
	colima start --cpu 4 --memory 8 --disk 40 --kubernetes

compose-up:
	docker compose up --build

k8s-install:
	helm upgrade --install myota deploy/helm/myota --namespace myota --create-namespace
