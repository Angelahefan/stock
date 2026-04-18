-- LSE / UK market i18n labels (8 languages)
-- nav_uk
INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES
('nav_uk', 'en', 'UK Stocks', 'nav'),
('nav_uk', 'zh', '英股', 'nav'),
('nav_uk', 'zh-TW', '英股', 'nav'),
('nav_uk', 'ja', '英国株', 'nav'),
('nav_uk', 'ko', '영국주식', 'nav'),
('nav_uk', 'vi', 'Co phieu Anh', 'nav'),
('nav_uk', 'th', 'หุ้นอังกฤษ', 'nav'),
('nav_uk', 'ms', 'Saham UK', 'nav')
ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text;

-- nav_uk_short
INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES
('nav_uk_short', 'en', 'United Kingdom', 'nav'),
('nav_uk_short', 'zh', '英国', 'nav'),
('nav_uk_short', 'zh-TW', '英國', 'nav'),
('nav_uk_short', 'ja', 'イギリス', 'nav'),
('nav_uk_short', 'ko', '영국', 'nav'),
('nav_uk_short', 'vi', 'Vuong quoc Anh', 'nav'),
('nav_uk_short', 'th', 'สหราชอาณาจักร', 'nav'),
('nav_uk_short', 'ms', 'United Kingdom', 'nav')
ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text;

-- hero_title_uk
INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES
('hero_title_uk', 'en', 'LSE Company Intelligence', 'hero'),
('hero_title_uk', 'zh', '伦交所公司情报', 'hero'),
('hero_title_uk', 'zh-TW', '倫交所公司情報', 'hero'),
('hero_title_uk', 'ja', 'LSE企業インテリジェンス', 'hero'),
('hero_title_uk', 'ko', 'LSE 기업 인텔리전스', 'hero'),
('hero_title_uk', 'vi', 'Phan tich cong ty LSE', 'hero'),
('hero_title_uk', 'th', 'ข่าวกรองบริษัท LSE', 'hero'),
('hero_title_uk', 'ms', 'Perisikan syarikat LSE', 'hero')
ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text;

-- hero_desc_uk
INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES
('hero_desc_uk', 'en', 'Monitor FTSE 100 & FTSE 250 companies for website changes that signal material events', 'hero'),
('hero_desc_uk', 'zh', '监控富时100和富时250公司网站变动,发现重大事件信号', 'hero'),
('hero_desc_uk', 'zh-TW', '監控富時100和富時250公司網站變動,發現重大事件信號', 'hero'),
('hero_desc_uk', 'ja', 'FTSE100・FTSE250企業のウェブサイト変更を監視し、重要イベントを検知', 'hero'),
('hero_desc_uk', 'ko', 'FTSE 100 및 FTSE 250 기업 웹사이트 변동을 모니터링하여 중요 이벤트 감지', 'hero'),
('hero_desc_uk', 'vi', 'Giam sat cac cong ty FTSE 100 & FTSE 250 de phat hien su kien quan trong', 'hero'),
('hero_desc_uk', 'th', 'ติดตามบริษัท FTSE 100 & FTSE 250 เพื่อตรวจจับเหตุการณ์สำคัญ', 'hero'),
('hero_desc_uk', 'ms', 'Pantau syarikat FTSE 100 & FTSE 250 untuk mengesan peristiwa penting', 'hero')
ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text;

-- section_uk_market
INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES
('section_uk_market', 'en', 'London Stock Exchange', 'section'),
('section_uk_market', 'zh', '伦敦证券交易所', 'section'),
('section_uk_market', 'zh-TW', '倫敦證券交易所', 'section'),
('section_uk_market', 'ja', 'ロンドン証券取引所', 'section'),
('section_uk_market', 'ko', '런던증권거래소', 'section'),
('section_uk_market', 'vi', 'So Giao dich Chung khoan London', 'section'),
('section_uk_market', 'th', 'ตลาดหลักทรัพย์ลอนดอน', 'section'),
('section_uk_market', 'ms', 'Bursa Saham London', 'section')
ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text;
