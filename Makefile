.PHONY: dist tests qa flake8 pylint mypy

dist:
	@- $(RM) -r build
	./setup.py sdist
	./setup.py bdist_wheel
	for f in dist/*.tar.gz dist/*.whl; do			\
	  case "$$f" in						\
	    *.dev*)						\
	      ;;						\
	    *)							\
	      test -e "$$f.asc"					\
	        && test "$$f.asc" -nt "$$f"			\
	        || gpg --armor --detach-sign --yes "$$f"	\
	      ;;						\
	  esac							\
	done
	scripts/bump-to-dev-version

tests:
	tox

qa: flake8 pylint mypy black

flake8:
	flake8 src/caterpillar tests

pylint:
	pylint src/caterpillar tests

mypy:
	mypy src/caterpillar

black:
	git ls-files | grep '\.py$$' | xargs black --check --diff
