# This is a sample Python script.

# Press Ctrl+F5 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.


import uvicorn



# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    print('PyCharm')
 
    uvicorn.run("openapi:app", host="0.0.0.0", port=8000, log_level="info", reload=False,\
         ssl_keyfile="/home/mquevedo/ozone_testnet.key", ssl_certfile="/home/mquevedo/ozone_testnet.crt")

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
""" 


openssl req -newkey rsa:4096 \
            -x509 \
            -sha256 \
            -days 3650 \
            -nodes \
            -out ozone_testnet.crt \
            -keyout ozone_testnet.key """