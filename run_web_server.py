# This is a sample Python script.

# Press Ctrl+F5 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.


import uvicorn



# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    print('PyCharm')
    uvicorn.run("ozoneapi.api:app", host="0.0.0.0", port=8000, log_level="info", reload=True)

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
 