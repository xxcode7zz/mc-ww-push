if __name__ == '__main__':
    from config import config
    from mcww.branding import bootstrap
    from ok import OK

    bootstrap()
    config = config
    config['debug'] = True
    # config['click_screenshots_folder'] = "click_screenshots"  # debug用 点击后截图文件夹]
    ok = OK(config)
    ok.start()
