<!-- dds {"document":"ai-support-proposal","design_system":"PlanningSystem","base":"https://example.org/data/","lang":"ko"} -->
# AI 상담 시스템 기획안

<!-- dds {"id":"overview","s":"Section"} -->
<!-- dds {"id":"overview-title","s":"Heading"} -->
## 프로젝트 개요

<!-- dds {"id":"overview-desc","s":"Paragraph","sem":["Description"]} -->
고객 환불 문의를 1차로 응대하는 AI 상담 시스템을 구축한다.

<!-- dds {"id":"REQ001","s":"Paragraph","sem":["Requirement"],"p":"Callout"} -->
> 환불 가능 여부를 판단해야 한다.

<!-- /dds {"id":"overview"} -->

<!-- dds {"id":"scope","s":"Section"} -->
<!-- dds {"id":"scope-title","s":"Heading"} -->
## 범위와 제약

<!-- dds {"id":"scope-list","s":"List","ordered":true,"items":[{"id":"CON001","sem":["Constraint","Policy"]},{"id":"scope-list-i2"}]} -->
1. 개인정보는 마스킹된 상태로만 처리한다.
2. 1차 범위는 환불 문의로 한정한다.

<!-- dds {"id":"scope-detail","s":"Section"} -->
<!-- dds {"id":"scope-detail-title","s":"Heading"} -->
### 가정과 근거

<!-- dds {"id":"ASM001","s":"Paragraph","sem":["Assumption"],"p":"Emphasis"} -->
**상담 이력 데이터는 6개월치가 확보되어 있다.**

<!-- /dds {"id":"scope-detail"} -->

<!-- /dds {"id":"scope"} -->

<!-- dds {"id":"decisions","s":"Section"} -->
<!-- dds {"id":"decisions-title","s":"Heading"} -->
## 의사결정 기록

<!-- dds {"id":"decision-table","s":"Table","rows":[{"id":"decision-table-r1","cells":[{"id":"decision-table-r1-c1"},{"id":"decision-table-r1-c2"},{"id":"decision-table-r1-c3"}]},{"id":"decision-table-r2","cells":[{"id":"decision-table-r2-c1"},{"id":"decision-table-r2-c2","sem":["Decision"]},{"id":"decision-table-r2-c3","sem":["Evidence"]}]}]} -->
| 항목 | 결정 | 근거 |
|---|---|---|
| 모델 호스팅 | 사내 호스팅 | 데이터 반출 금지 정책 |

<!-- /dds {"id":"decisions"} -->
