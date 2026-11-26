/* ============================================================
   Q2.1 商品类别翻译完整性分析
   Database: MySQL 8.4
   Dataset: Olist

   分析目标：
   识别商品表中存在、但缺少英文翻译的商品类别，
   并统计每个类别涉及的商品数量。

   分析流程：
   1. 检查数据表结构及约束；
   2. 验证商品表的数据粒度及类别字段完整性；
   3. 验证翻译表的英文映射完整性；
   4. 明确缺失翻译的统计口径；
   5. 执行查询并解释结果。
   ============================================================ */


/* ============================================================
   Step 1. 数据表结构检查
   ============================================================ */

-- 需要检查实际字段类型、主键及 NULL 约束。

SHOW CREATE TABLE `olist`.`olist_products_dataset.csv`;

SHOW CREATE TABLE `olist`.`product_category_name_translation.csv`;

-- 关注以下问题：
-- 1. product_id 是否为主键，决定商品表的数据粒度；
-- 2. product_category_name 是否允许 NULL；
-- 3. 翻译表中的葡萄牙语类别名是否唯一；
-- 4. 英文类别名是否允许 NULL。
--
-- 翻译表类别名的唯一性尤其重要：
-- 如果同一个类别存在多条映射记录，JOIN 后可能产生行数膨胀，
-- 进而导致商品数量被重复统计。


/* ============================================================
   Step 2. 商品表数据质量检查
   ============================================================ */

-- 在统计缺失翻译之前，需要区分两类不同的数据质量问题：
--
-- 1. 商品本身没有类别名称：
--    属于商品分类信息缺失。
--
-- 2. 商品具有明确的葡萄牙语类别名称，但没有英文翻译：
--    属于类别翻译映射不完整。
-- 即先判断是否有具体类别名称，再判断有没有翻译
--
-- 同时比较总记录数与唯一商品 ID 数，
-- 验证是否可以使用 COUNT(*) 直接统计商品数量。

SELECT
    COUNT(*) AS product_rows,

    COUNT(DISTINCT product_id) AS unique_product_ids,

    COUNT(
        CASE
            WHEN product_category_name IS NULL
            THEN 1
        END
    ) AS null_category_rows,

    COUNT(
        CASE
            WHEN product_category_name IS NOT NULL
             AND TRIM(product_category_name) = ''
            THEN 1
        END
    ) AS blank_category_rows

FROM `olist`.`olist_products_dataset.csv`;


/* ============================================================
   Step 3. 翻译表数据质量检查
   ============================================================ */

-- 翻译表中存在葡萄牙语类别记录，
-- 并不一定意味着该类别已经具有有效的英文翻译。
--
-- 需要进一步检查英文名称是否为 NULL 或空字符串。
--
-- 如果只判断类别能否成功 JOIN，
-- 可能遗漏已经建立映射记录、但英文翻译内容为空的类别。

SELECT
    COUNT(*) AS translation_rows,

    COUNT(DISTINCT product_category_name)
        AS unique_categories,

    COUNT(
        CASE
            WHEN product_category_name_english IS NULL
            THEN 1
        END
    ) AS null_english_rows,

    COUNT(
        CASE
            WHEN product_category_name_english IS NOT NULL
             AND TRIM(product_category_name_english) = ''
            THEN 1
        END
    ) AS blank_english_rows

FROM `olist`.`product_category_name_translation.csv`;


/* ============================================================
   Step 4. 确定业务统计口径
   ============================================================ */

-- 将“缺失英文翻译”定义为：
--
-- 1. 商品具有明确且非空的葡萄牙语类别名称；
-- 2. 该类别在翻译表中不存在对应记录，
--    或存在对应记录但没有有效的英文名称。
--
-- 不将商品类别本身为 NULL 或空字符串的记录纳入统计，
-- 因为此时缺失的是商品分类信息，而不仅仅是英文翻译。
--
-- 使用 LEFT JOIN 而非 INNER JOIN：
-- INNER JOIN 会直接过滤掉无法匹配翻译表的商品，
-- 而这些记录正是本题需要识别的目标。
--
-- 在确认商品 ID 唯一、翻译表类别名唯一后，
-- 使用 COUNT(*) 统计每个缺失翻译类别涉及的商品数量。


/* ============================================================
   Step 5. Q2.1 核心查询
   ============================================================ */

SELECT
    p.product_category_name,
    COUNT(*) AS product_count

FROM `olist`.`olist_products_dataset.csv` AS p

LEFT JOIN `olist`.`product_category_name_translation.csv` AS t
    ON p.product_category_name = t.product_category_name

WHERE
    -- 排除商品类别本身缺失的记录
    p.product_category_name IS NOT NULL
    AND TRIM(p.product_category_name) <> ''

    -- 识别没有有效英文翻译的类别
    AND (
        t.product_category_name IS NULL
        OR t.product_category_name_english IS NULL
        OR TRIM(t.product_category_name_english) = ''
    )

-- 按葡萄牙语原始类别聚合，保留类别的业务含义
GROUP BY
    p.product_category_name

-- 优先展示影响商品数量较多的类别，
-- 为后续翻译修复确定优先级。
-- 当商品数量相同时，按照类别名称排序，保证结果稳定。
ORDER BY
    product_count DESC,
    p.product_category_name;


/* ============================================================
   Step 6. 具体分析
   ============================================================ */

-- 根据此前查询结果：
--
-- 1. 商品表中存在 2 个具有明确类别名称、
--    但未匹配到翻译记录的类别，共涉及 13 个商品。
--
-- 2. 另有 610 个商品的类别字段为 NULL。
--    这些商品属于分类信息缺失，不纳入上述两个类别的统计。
--
-- 3. 如果下游业务分析直接使用 INNER JOIN 连接翻译表，
--    缺少映射记录的商品将无法进入分析结果，
--    可能造成商品数量、销售额和类别贡献度统计偏差。
--
-- 4. 如果仅按英文类别名称进行 GROUP BY，
--    不同的未翻译类别可能被合并到同一个 NULL 分组，
--    导致原始类别信息丢失。
--
-- 因此，后续数据处理应保留葡萄牙语原始类别名称，
-- 并对分类缺失和翻译缺失分别进行标记和处理。
--
-- 进阶：对于这些缺失翻译的类别，你会如何处理？给出 3 种方案及利弊。
-- 1.人工查询后补充 （优点：准确；缺点：耗费人力，成本高）
-- 2.不修改，保留葡萄牙语（优点：省事；缺点：不利于后续分析）
-- 3.机器翻译（优点：既不影响后续分析，还节省人力；缺点：准确性低）
