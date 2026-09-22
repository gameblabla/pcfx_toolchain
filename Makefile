.PHONY: help doctor host-tools toolchain sdk headless all release verify clean

help:
	@printf '%s\n' \
		'PC-FX toolkit targets:' \
		'  doctor       check dependencies and optional BIOS/toolchain state' \
		'  host-tools   build original and large-game host tools' \
		'  toolchain    install V810_GCC into toolchain/ or build it with --build' \
		'  sdk          build libpcfx and install the SDK' \
		'  headless     build pcfx-headless and pcfx-headless-prof' \
		'  all          host-tools + toolchain + sdk + headless' \
		'  release      package the current source and bundled binaries' \
		'  verify       run local structural and script checks' \
		'  clean        remove top-level build/dist/toolchain products'

doctor:
	./scripts/doctor.sh

host-tools:
	./scripts/build-host-tools.sh

toolchain:
	./scripts/build-toolchain.sh

sdk:
	./scripts/build-sdk.sh

headless:
	./scripts/build-headless.sh

all: host-tools toolchain sdk headless

release: all
	./scripts/package-release.sh

verify:
	./scripts/verify-release.sh

clean:
	rm -rf build dist toolchain
