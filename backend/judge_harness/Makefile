# The code judge harness (ADR-0042). The backend image builds it in its own
# Dockerfile stage; these targets are for a source checkout.
#
#   make            build bin/harness-linux-{amd64,arm64} (needs Go)
#   make docker     the same, in a golang container (no local Go needed)
#   make test       the unit tests, as root in a golang container — they drop
#                   privileges to the submission user, which needs root

GO_IMAGE ?= golang:1.27
ARCHES   := amd64 arm64
SOURCES  := $(wildcard *.go) go.mod

build: $(ARCHES:%=bin/harness-linux-%)

bin/harness-linux-%: $(SOURCES)
	CGO_ENABLED=0 GOOS=linux GOARCH=$* go build -trimpath -ldflags="-s -w" -o $@ .

docker:
	docker run --rm -u "$$(id -u):$$(id -g)" -e HOME=/tmp -e GOFLAGS=-buildvcs=false \
		-v "$(CURDIR)":/src -w /src $(GO_IMAGE) make build

test:
	docker run --rm -e GOFLAGS=-buildvcs=false -v "$(CURDIR)":/src -w /src $(GO_IMAGE) \
		sh -c 'test -z "$$(gofmt -l .)" && go vet ./... && go test -count=1 ./...'

.PHONY: build docker test
