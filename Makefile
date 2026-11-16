# PlantWatch - one-command entry points. Everything except `report` needs sudo:
#   sudo make setup && sudo make up && sudo make test && sudo make experiments
SHELL := /bin/bash
.PHONY: setup preflight up down status test A B C D E F experiments report demo clean

setup:        ## install packages, Python env, certificates, dataset (run once)
	bash lab/setup_host.sh
preflight:    ## check kernel features (netem, nftables, namespaces)
	bash lab/preflight.sh
up:           ## build the network and start all services
	bash lab/up.sh
down:         ## stop services and remove the network
	bash lab/down.sh
status:       ## service and link status
	bash lab/services.sh status
test:         ## automated configuration validation / health checks
	bash experiments/validate.sh
A:            ## Module A evidence: network infrastructure
	bash experiments/A_network.sh
B:            ## Module B evidence: service + Redis queries
	bash experiments/B_service.sh
C:            ## Module C evidence: firewall + TLS, allowed and denied
	bash experiments/C_security.sh
D:            ## Module D evidence: packet captures, logs, correlation
	bash experiments/D_observability.sh
E:            ## Module E evidence: baseline vs degraded network
	bash experiments/E_performance.sh
F:            ## Module F evidence: failure injection and automated recovery
	bash experiments/F_recovery.sh
experiments:  ## run everything and build evidence/results.md
	bash experiments/run_all.sh
report:       ## rebuild evidence/results.md and charts from existing raw data
	@if [ -x .venv/bin/python ]; then .venv/bin/python experiments/make_report.py; else python3 experiments/make_report.py; fi
demo:         ## replay 200 dataset rows as live telemetry from the plant zone
	bash -c '. lab/env.sh; ip netns exec $$NS_PLANT $$PY client/replay.py --count 200 --rate 20'
clean:        ## remove generated evidence and runtime state (keeps certificates and .env)
	bash lab/down.sh; rm -rf evidence/* run/redis run/logs run/*.pid run/redis.conf
