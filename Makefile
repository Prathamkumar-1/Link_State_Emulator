all: VN

VN: VN.cpp
	g++ -o VN VN.cpp

clean:
	rm -f VN