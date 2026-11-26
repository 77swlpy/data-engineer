/* ============================================================
   Q2.3
   考虑订单数和商品数（卖家）并非一一对应
   需要给出一个统计维度
   一行是一个商家和一个订单
   时间沿用上一问：以购买时间为标准
   GMV有多种状态，ai建议继续沿用用q2.2定义，但是2017全年GMV我认为应该需要考虑的是包括取消状态拆解的全状态
   评价体系需要规定，一个订单可能由多个商品评价组成，是否使用平均评分？
   问题一（卡点）具体怎么去重？这一块没什么思路，是问的ai得出
   ai：同一订单具有不同评分时，仍然会保留多条记录；而具有相同评分的不同评价也不一定是重复记录。
   事实上我问之前已经想到了需要去除1.一个订单可能由多个商品评价组成，这部分会产生重复
   ai补充了另外一种情况就是完全相同的评价记录重复出现
   上述两情况都需要去重
   问题二（卡点）：如果使用平均评分，会不会影响商家评分判断，同一订单不同收获日期产生多个评价，是否需要结合这个对商家评分的影响
   这个关系到州内排名
   ai：重复评分不止有不同送达日期这一种影响条件，需要综合考量
       平均评分能够保留整体评价信息，但会掩盖评价变化方向；最新评分能够反映最后一次记录的满意度，但可能忽略此前真实发生的问题。
   问题三：按这么说的话，没有什么评分体系可以很好的解决这个问题
   
   附加：由于问题二三发现了数据集的一个缺陷
        评价表没有 seller_id 或 order_item_id，商品明细表也没有商品级实际收货时间。
        因此，即使同一个订单存在多个卖家和多条评价，也无法准确确定：
        哪条评价对应哪个卖家；
        哪条评价对应哪个商品；
        商品是否分批送达；
        评分变化是否由物流延迟引起。
        接6.2 建议以后数据采集的时候加上这两个字段，方便后续细化卖家评价（后续进一步细化）
   ============================================================ */
   
   -- ① 卖家表
SHOW COLUMNS
FROM `olist`.`olist_sellers_dataset.csv`;

-- ② 客户表
SHOW COLUMNS
FROM `olist`.`olist_customers_dataset.csv`;

-- ③ 评价表
SHOW COLUMNS
FROM `olist`.`olist_order_reviews_dataset.csv`;

-- 先数据检查，解决问题二三：不同评价到底是相同评分居多，还是存在明显的评分冲突
SELECT
    order_id,
    COUNT(*) AS review_count,
    COUNT(DISTINCT review_id) AS unique_review_count,
    COUNT(DISTINCT review_score) AS distinct_score_count,
    MIN(review_score) AS min_score,
    MAX(review_score) AS max_score,
    MAX(review_score) - MIN(review_score) AS score_range,
    MIN(review_answer_timestamp) AS first_review_time,
    MAX(review_answer_timestamp) AS last_review_time
FROM `olist`.`olist_order_reviews_dataset.csv`
GROUP BY order_id
HAVING COUNT(*) > 1
ORDER BY score_range DESC, review_count DESC;

-- 可以看到score_range中大部分都是0和1，分差较小

-- 然后检查多评价订单是否涉及多个卖家
WITH multi_review_orders AS (
    SELECT
        order_id,
        COUNT(*) AS review_count,
        COUNT(DISTINCT review_score) AS distinct_score_count
    FROM `olist`.`olist_order_reviews_dataset.csv`
    GROUP BY order_id
    HAVING COUNT(*) > 1
),

order_sellers AS (
    SELECT
        order_id,
        COUNT(DISTINCT seller_id) AS seller_count
    FROM `olist`.`olist_order_items_dataset.csv`
    GROUP BY order_id
)

SELECT
    r.order_id,
    r.review_count,
    r.distinct_score_count,
    s.seller_count
FROM multi_review_orders AS r
LEFT JOIN order_sellers AS s
    ON r.order_id = s.order_id
ORDER BY
    s.seller_count DESC,
    r.distinct_score_count DESC;
   
   -- 大多数都是同一个卖家（（97.26%）个人认为还是使用平均分比较合理）
    -- 统计后发现这些结果怎么有不同订单具有完全相同的评价时间范围和评分区间
    -- 是错误数据吗还是同一个 review_id 是否被关联到了多个不同订单，产生问题四（卡点）这要怎么判断归属问题
    -- 进一步检查这是什么问题
    -- 检查同一评价 ID 是否关联多个不同订单。
-- 判断评价记录是否具有跨订单复用现象，
-- 避免将评价 ID 直接假定为全局唯一标识。

SELECT
    review_id,
    COUNT(*) AS review_rows,
    COUNT(DISTINCT order_id) AS order_count,
    COUNT(DISTINCT review_score) AS distinct_score_count,
    MIN(review_score) AS min_score,
    MAX(review_score) AS max_score
FROM `olist`.`olist_order_reviews_dataset.csv`
GROUP BY review_id
HAVING COUNT(DISTINCT order_id) > 1
ORDER BY order_count DESC, review_id;
-- 综合来看，order_id 与 review_id 在整个数据集中存在多对多映射关系。
-- 不能直接按照 review_id 进行全局去重
-- ai建议两阶段去重，我认为这个方法比较合理
-- 第一阶段：建立订单—评价唯一关系
-- 以 order_id + review_id 作为评价关联的业务键。
-- 保留不同订单与同一评价 ID 的关联关系，仅合并同一订单下同一评价 ID 的重复记录。
-- MAX() 确认同一订单、同一评价 ID 的评分一致后，提取唯一评分。
-- 第二阶段：统一为订单级评分
-- 检查同一订单下的同一评价 ID 是否存在不同评分
-- 以 order_id + review_id 作为评价关联的业务键。
-- 保留同一评价 ID 与不同订单的映射关系，
-- 避免全局去重导致评价归属信息丢失。
-- MAX() 的使用以同一组合内评分一致为前提。

WITH review_dedup AS (
    SELECT
        order_id,
        review_id,
        MAX(review_score) AS review_score
    FROM `olist`.`olist_order_reviews_dataset.csv`
    WHERE review_score BETWEEN 1 AND 5
    GROUP BY
        order_id,
        review_id
)

SELECT *
FROM review_dedup;
WITH review_dedup AS (

    -- 第一阶段：订单—评价级去重
    -- 保留跨订单评价映射，仅合并同一订单下的重复评价。
    SELECT
        order_id,
        review_id,
        MAX(review_score) AS review_score
    FROM `olist`.`olist_order_reviews_dataset.csv`
    WHERE review_score BETWEEN 1 AND 5
    GROUP BY
        order_id,
        review_id

),

order_review AS (

    -- 第二阶段：将评价粒度统一为订单级
    -- 保留同一订单的多条有效评价信息，
    -- 避免多评价订单在卖家平均评分中获得额外权重。
    SELECT
        order_id,
        COUNT(*) AS review_count,
        AVG(review_score) AS order_review_score
    FROM review_dedup
    GROUP BY order_id

)

-- 查看存在多条有效评价的订单及其订单级平均评分
SELECT *
FROM order_review
WHERE review_count > 1
ORDER BY review_count DESC, order_id;



-- 对 TOP 20 卖家评分的实际影响
/*
========================================================
Q2.3 卖家维度分析
数据集：Olist
数据库：MySQL 8.0+

统计口径：
1. 时间范围：2017-01-01 至 2017-12-31
2. GMV：仅统计已送达订单，price + freight_value
3. 订单数：统计卖家参与的全部订单，不限订单状态
4. 独立客户数：使用 customer_unique_id 去重
5. 平均评分：订单内平均评分，再对订单等权平均
6. 延迟送达率：实际送达日期晚于预计送达日期的比例
7. 取消率：取消订单数 / 卖家全部订单数
8. 州内排名：按 GMV 使用 RANK() 计算
9. 最终输出：全国 GMV TOP 20 卖家

注意：
订单级评价无法准确归属到订单内的具体卖家，
多卖家订单的评价会被关联至参与该订单的卖家。
========================================================
*/

WITH

-- =====================================================
-- 1. 筛选2017年订单，保留全部订单状态
-- =====================================================
orders_2017 AS (

    SELECT
        order_id,
        customer_id,
        order_status,
        order_purchase_timestamp,
        order_delivered_customer_date,
        order_estimated_delivery_date

    FROM `olist`.`olist_orders_dataset.csv`

    WHERE order_purchase_timestamp >= '2017-01-01'
      AND order_purchase_timestamp < '2018-01-01'

),

-- =====================================================
-- 2. 商品明细聚合
-- 统一为卖家—订单级，避免多商品重复统计订单
-- 统计全部订单状态下可归属该卖家的明细金额，金额为 price + freight_value。（ai给的是送达修正为全状态）
-- =====================================================
seller_order_items AS (

    SELECT
        oi.seller_id,
        oi.order_id,

        SUM(oi.price + oi.freight_value) AS order_gmv

    FROM `olist`.`olist_order_items_dataset.csv` AS oi

    INNER JOIN orders_2017 AS o
        ON oi.order_id = o.order_id

    GROUP BY
        oi.seller_id,
        oi.order_id

),

-- =====================================================
-- 3. 评价去重
-- 以 order_id + review_id 作为评价关联的业务键
-- 保留同一评价ID与不同订单之间的映射关系
-- MAX使用前提：同一组合内评分一致
-- =====================================================
review_dedup AS (

    SELECT
        order_id,
        review_id,
        MAX(review_score) AS review_score

    FROM `olist`.`olist_order_reviews_dataset.csv`

    WHERE review_score BETWEEN 1 AND 5

    GROUP BY
        order_id,
        review_id

),

-- =====================================================
-- 4. 订单级平均评分
-- 每个订单最终只保留一个平均评分
-- 避免多评价订单获得额外权重
-- =====================================================
order_review AS (

    SELECT
        order_id,
        AVG(review_score) AS order_review_score

    FROM review_dedup

    GROUP BY order_id

),

-- =====================================================
-- 5. 构建卖家—订单级基础数据
-- 每行代表一个卖家参与的一个订单
-- =====================================================
seller_order_base AS (

    SELECT
        soi.seller_id,
        soi.order_id,

        o.customer_id,
        c.customer_unique_id,

        o.order_status,

        o.order_purchase_timestamp,
        o.order_delivered_customer_date,
        o.order_estimated_delivery_date,

        soi.order_gmv,

        r.order_review_score

    FROM seller_order_items AS soi

    INNER JOIN orders_2017 AS o
        ON soi.order_id = o.order_id

    LEFT JOIN `olist`.`olist_customers_dataset.csv` AS c
        ON o.customer_id = c.customer_id

    LEFT JOIN order_review AS r
        ON soi.order_id = r.order_id

),

-- =====================================================
-- 6. 计算卖家维度指标
-- 所有指标均基于卖家—订单级数据
-- =====================================================
seller_metrics AS (

    SELECT

        seller_id,

        
        -- 2017年全状态GMV：
        -- 汇总该卖家在各订单中的商品金额及运费，包含取消等状态。
          SUM(order_gmv) AS gmv_2017,
        -- 卖家参与的全部订单数
        COUNT(DISTINCT order_id) AS order_count,

        -- 不重复客户数
        COUNT(DISTINCT customer_unique_id) AS unique_customers,

        -- 订单内平均评分，再对订单等权平均
        AVG(order_review_score) AS avg_review_score,

        -- 延迟送达订单数
        SUM(
            CASE
                WHEN order_status = 'delivered'
                 AND order_delivered_customer_date IS NOT NULL
                 AND order_estimated_delivery_date IS NOT NULL
                 AND order_purchase_timestamp IS NOT NULL
                 AND order_delivered_customer_date
                     >= order_purchase_timestamp
                 AND DATE(order_delivered_customer_date)
                     > DATE(order_estimated_delivery_date)
                THEN 1
                ELSE 0
            END
        ) AS late_orders,

        -- 有效送达时间订单数：延迟率分母
        SUM(
            CASE
                WHEN order_status = 'delivered'
                 AND order_delivered_customer_date IS NOT NULL
                 AND order_estimated_delivery_date IS NOT NULL
                 AND order_purchase_timestamp IS NOT NULL
                 AND order_delivered_customer_date
                     >= order_purchase_timestamp
                THEN 1
                ELSE 0
            END
        ) AS valid_delivery_orders,

        -- 取消订单数
        SUM(
            CASE
                WHEN order_status = 'canceled'
                THEN 1
                ELSE 0
            END
        ) AS canceled_orders

    FROM seller_order_base

    GROUP BY seller_id

),

-- =====================================================
-- 7. 关联卖家所在州，计算延迟率和取消率
-- =====================================================
seller_final AS (

    SELECT

        m.seller_id,
        s.seller_state,

        m.gmv_2017,
        m.order_count,
        m.unique_customers,

        ROUND(m.avg_review_score, 2)
            AS avg_review_score,

        -- 延迟送达率（百分比）
        ROUND(
            100.0 * m.late_orders
            / NULLIF(m.valid_delivery_orders, 0),
            2
        ) AS late_delivery_rate,

        -- 取消率（百分比）
        ROUND(
            100.0 * m.canceled_orders
            / NULLIF(m.order_count, 0),
            2
        ) AS cancel_rate

    FROM seller_metrics AS m

    LEFT JOIN `olist`.`olist_sellers_dataset.csv` AS s
        ON m.seller_id = s.seller_id

),

-- =====================================================
-- 8. 计算完整卖家集合中的州内GMV排名
-- =====================================================
seller_ranked AS (

    SELECT

        seller_id,
        seller_state,
        gmv_2017,
        order_count,
        unique_customers,
        avg_review_score,
        late_delivery_rate,
        cancel_rate,

        RANK() OVER (
            PARTITION BY seller_state
            ORDER BY gmv_2017 DESC
        ) AS state_rank,

        ROW_NUMBER() OVER (
            ORDER BY gmv_2017 DESC, seller_id
        ) AS global_rank

    FROM seller_final

)

-- =====================================================
-- 9. 输出全国GMV TOP 20
-- =====================================================
SELECT

    seller_id,
    seller_state,
    gmv_2017,
    order_count,
    unique_customers,
    avg_review_score,
    late_delivery_rate,
    cancel_rate,
    state_rank

FROM seller_ranked

WHERE global_rank <= 20

ORDER BY
    gmv_2017 DESC,
    seller_id;
    
-- 延迟送达率
-- 采用：LateRate={延迟送达订单数}÷{有效送达时间订单数}*100%
-- 取消率
-- CancelRate={取消订单数}÷{卖家参与的全部订单数}*100%
