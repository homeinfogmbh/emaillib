FILE_LIST = ./.installed_files.txt

.PHONY: pull push clean publish install uninstall pypi

default: | pull clean install

install:
	@ ./setup.py install --record $(FILE_LIST)

uninstall:
	@ while read FILE; do echo "Removing: $$FILE"; rm "$$FILE"; done < $(FILE_LIST)

clean:
	@ rm -Rf ./build

publish:
	@ twine upload dist/*

pull:
	@ git pull

push:
	@ git push

pypi: | build publish clean
