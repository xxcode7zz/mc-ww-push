if __name__ == '__main__':
    from config import config
    from mcww.branding import bootstrap
    from ok import OK

    # 品牌启动准备必须早于 OK(config)：运行时补丁要赶在 UI 构建前打上，
    # 翻译回退也要赶在第一批 tr() 调用前挂好。
    bootstrap()
    config = config
    ok = OK(config)
    ok.start()
