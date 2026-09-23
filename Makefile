.PHONY: test run compose-up colima-start k8s-install

test:
	python3 -m unittest discover -s tests -v

run:
	python3 services/dev_server.py

colima-start:
	colima start --cpu 4 --memory 8 --disk 40 --kubernetes

compose-up:
	docker compose up --build

k8s-install:
	helm upgrade --install myota deploy/helm/myota --namespace myota --create-namespace

