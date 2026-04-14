# uncompyle6 version 3.9.3
# Python bytecode version base 3.8.0 (3413)
# Decompiled from: Python 3.9.6 (default, Nov 11 2024, 03:15:38) 
# [Clang 16.0.0 (clang-1600.0.26.6)]
# Embedded file name: /home/ec2-user/git/datapai-stock-be/scripts/lib/twenty_client.py
# Compiled at: 2026-04-11 20:04:31
# Size of source mod 2**32: 16480 bytes
"""
scripts/lib/twenty_client.py
─────────────────────────────────────────────────────────────────────────────
Thin GraphQL client for Twenty CRM v1.21+ — used by the stock CRM sync DAG
and (future) the AI chatbot tool-call layer.

Twenty exposes two GraphQL endpoints:
  - /metadata : schema/object/field management + system queries
  - /graphql  : workspace data (records in stockClient, person, company, etc.)

This client wraps both with a single API-key bearer token (generated via the
Twenty UI Settings → APIs & Webhooks, or programmatically via createApiKey +
generateApiKeyToken as we did in Phase 1.4.6b).

Auth:
  Authorization: Bearer $TWENTY_STOCK_API_KEY

Design goals:
  1. Tiny dependency surface — only httpx (already in the platform requirements)
  2. Same logging + retry style as db_helpers.py
  3. Idempotent upsert by arbitrary dedup field (not just id)
  4. Batch-aware — Twenty supports array create mutations natively
  5. Enum normalisation helper — Twenty SELECT values must be UPPER_SNAKE_CASE,
     but Postgres check constraints are lowercase; the sync script can call
     this once per field value instead of sprinkling .upper() everywhere

Usage:
    from scripts.lib.twenty_client import TwentyClient, upper_enum
    client = TwentyClient.from_env()                  # reads env vars
    client.ping()                                     # smoke test

    existing = client.find_one("stockClient", filter={"email": {"eq": "donny@datap.ai"}},
                               fields=["id", "email", "subscriptionPlan"])
    if existing:
        client.update_record("stockClient", existing["id"], {"deviceCount": 2})
    else:
        client.create_record("stockClient", {
            "email": "donny@datap.ai",
            "signupSource": upper_enum("web"),        # -> "WEB"
            "subscriptionPlan": upper_enum("individual"),
        })

    # Bulk upsert (used by the sync DAG)
    result = client.bulk_upsert(
        "stockClient",
        rows=[
            {"email": "a@x.com", "deviceCount": 1},
            {"email": "b@x.com", "deviceCount": 3},
        ],
        dedup_field="email",
    )
    # result = {"created": N, "updated": M, "failed": K}
"""
-- Stacks of completed symbols:
START ::= |- stmts . 
_come_froms ::= \e__come_froms . COME_FROM
_come_froms ::= \e__come_froms . COME_FROM_LOOP
_come_froms ::= \e__come_froms COME_FROM . 
_come_froms ::= _come_froms . COME_FROM
_come_froms ::= _come_froms . COME_FROM_LOOP
_ifstmts_jump ::= \e_c_stmts_opt . COME_FROM
_ifstmts_jump ::= \e_c_stmts_opt . ELSE
_ifstmts_jump ::= \e_c_stmts_opt . JUMP_ABSOLUTE JUMP_FORWARD \e__come_froms
_ifstmts_jump ::= \e_c_stmts_opt . JUMP_ABSOLUTE JUMP_FORWARD _come_froms
_ifstmts_jump ::= \e_c_stmts_opt . come_froms
_ifstmts_jump ::= c_stmts_opt . COME_FROM
_ifstmts_jump ::= c_stmts_opt . ELSE
_ifstmts_jump ::= c_stmts_opt . JUMP_ABSOLUTE JUMP_FORWARD \e__come_froms
_ifstmts_jump ::= c_stmts_opt . JUMP_ABSOLUTE JUMP_FORWARD _come_froms
_ifstmts_jump ::= c_stmts_opt . come_froms
_ifstmts_jump ::= c_stmts_opt COME_FROM . 
_ifstmts_jump ::= c_stmts_opt come_froms . 
_ifstmts_jumpl ::= _ifstmts_jump . 
_ifstmts_jumpl ::= c_stmts . JUMP_BACK
_stmts ::= _stmts . stmt
_stmts ::= _stmts stmt . 
_stmts ::= stmt . 
add_consts ::= \e_add_consts . ADD_VALUE
add_consts ::= \e_add_consts ADD_VALUE . 
add_consts ::= add_consts . ADD_VALUE
add_consts ::= add_consts ADD_VALUE . 
and ::= expr . JUMP_IF_FALSE_OR_POP expr \e_come_from_opt
and ::= expr . JUMP_IF_FALSE_OR_POP expr come_from_opt
and ::= expr . jifop_come_from expr
and ::= expr . jmp_false expr
and ::= expr . jmp_false expr COME_FROM
and ::= expr . jmp_false expr jmp_false
and ::= expr jmp_false . expr
and ::= expr jmp_false . expr COME_FROM
and ::= expr jmp_false . expr jmp_false
and ::= expr jmp_false expr . 
and ::= expr jmp_false expr . COME_FROM
and ::= expr jmp_false expr . jmp_false
and_not ::= expr . jmp_false expr POP_JUMP_IF_TRUE
and_not ::= expr jmp_false . expr POP_JUMP_IF_TRUE
and_not ::= expr jmp_false expr . POP_JUMP_IF_TRUE
assert2 ::= expr . jmp_true LOAD_GLOBAL expr CALL_FUNCTION_1 RAISE_VARARGS_1
assign ::= expr . DUP_TOP designList
assign ::= expr . store
assign ::= expr store . 
assign2 ::= expr . expr ROT_TWO store store
assign2 ::= expr expr . ROT_TWO store store
assign3 ::= expr . expr expr ROT_THREE ROT_TWO store store store
assign3 ::= expr expr . expr ROT_THREE ROT_TWO store store store
assign3 ::= expr expr expr . ROT_THREE ROT_TWO store store store
async_for_stmt38 ::= expr . async_for store for_block COME_FROM_FINALLY END_ASYNC_FOR
async_forelse_stmt38 ::= expr . GET_AITER SETUP_FINALLY GET_ANEXT LOAD_CONST YIELD_FROM POP_BLOCK store for_block COME_FROM_FINALLY END_ASYNC_FOR else_suite
attribute ::= expr . LOAD_ATTR
attribute ::= expr LOAD_ATTR . 
attribute37 ::= expr . LOAD_METHOD
attribute37 ::= expr LOAD_METHOD . 
aug_assign1 ::= expr . expr inplace_op ROT_THREE STORE_SUBSCR
aug_assign1 ::= expr . expr inplace_op store
aug_assign1 ::= expr expr . inplace_op ROT_THREE STORE_SUBSCR
aug_assign1 ::= expr expr . inplace_op store
aug_assign2 ::= expr . DUP_TOP LOAD_ATTR expr inplace_op ROT_TWO STORE_ATTR
await_expr ::= expr . GET_AWAITABLE LOAD_CONST YIELD_FROM
bin_op ::= expr . expr binary_operator
bin_op ::= expr expr . binary_operator
bin_op ::= expr expr binary_operator . 
binary_operator ::= BINARY_ADD . 
binary_operator ::= BINARY_AND . 
c_stmts ::= _stmts . 
c_stmts ::= _stmts . lastc_stmt
c_stmts ::= _stmts lastc_stmt . 
c_stmts_opt ::= c_stmts . 
call ::= expr . CALL_METHOD_0
call ::= expr . pos_arg CALL_FUNCTION_1
call ::= expr . pos_arg CALL_METHOD_1
call ::= expr . pos_arg pos_arg CALL_FUNCTION_2
call ::= expr . pos_arg pos_arg CALL_METHOD_2
call ::= expr . pos_arg pos_arg pos_arg CALL_FUNCTION_3
call ::= expr . pos_arg pos_arg pos_arg CALL_METHOD_3
call ::= expr . pos_arg pos_arg pos_arg pos_arg CALL_METHOD_4
call ::= expr . pos_arg pos_arg pos_arg pos_arg pos_arg pos_arg CALL_METHOD_6
call ::= expr CALL_METHOD_0 . 
call ::= expr pos_arg . CALL_FUNCTION_1
call ::= expr pos_arg . CALL_METHOD_1
call ::= expr pos_arg . pos_arg CALL_FUNCTION_2
call ::= expr pos_arg . pos_arg CALL_METHOD_2
call ::= expr pos_arg . pos_arg pos_arg CALL_FUNCTION_3
call ::= expr pos_arg . pos_arg pos_arg CALL_METHOD_3
call ::= expr pos_arg . pos_arg pos_arg pos_arg CALL_METHOD_4
call ::= expr pos_arg . pos_arg pos_arg pos_arg pos_arg pos_arg CALL_METHOD_6
call ::= expr pos_arg CALL_FUNCTION_1 . 
call ::= expr pos_arg pos_arg . CALL_FUNCTION_2
call ::= expr pos_arg pos_arg . CALL_METHOD_2
call ::= expr pos_arg pos_arg . pos_arg CALL_FUNCTION_3
call ::= expr pos_arg pos_arg . pos_arg CALL_METHOD_3
call ::= expr pos_arg pos_arg . pos_arg pos_arg CALL_METHOD_4
call ::= expr pos_arg pos_arg . pos_arg pos_arg pos_arg pos_arg CALL_METHOD_6
call ::= expr pos_arg pos_arg CALL_FUNCTION_2 . 
call ::= expr pos_arg pos_arg pos_arg . CALL_FUNCTION_3
call ::= expr pos_arg pos_arg pos_arg . CALL_METHOD_3
call ::= expr pos_arg pos_arg pos_arg . pos_arg CALL_METHOD_4
call ::= expr pos_arg pos_arg pos_arg . pos_arg pos_arg pos_arg CALL_METHOD_6
call ::= expr pos_arg pos_arg pos_arg pos_arg . CALL_METHOD_4
call ::= expr pos_arg pos_arg pos_arg pos_arg . pos_arg pos_arg CALL_METHOD_6
call ::= expr pos_arg pos_arg pos_arg pos_arg pos_arg . pos_arg CALL_METHOD_6
call ::= expr pos_arg pos_arg pos_arg pos_arg pos_arg pos_arg . CALL_METHOD_6
call_kw36 ::= expr . expr expr LOAD_CONST CALL_FUNCTION_KW_2
call_kw36 ::= expr expr . expr LOAD_CONST CALL_FUNCTION_KW_2
call_kw36 ::= expr expr expr . LOAD_CONST CALL_FUNCTION_KW_2
call_kw36 ::= expr expr expr LOAD_CONST . CALL_FUNCTION_KW_2
call_kw36 ::= expr expr expr LOAD_CONST CALL_FUNCTION_KW_2 . 
call_stmt ::= call . 
call_stmt ::= expr . POP_TOP
cf_jf_else ::= come_froms . JUMP_FORWARD ELSE
cf_jump_back ::= COME_FROM . JUMP_BACK
cf_pt ::= COME_FROM . POP_TOP
classdefdeco1 ::= expr . classdefdeco1 CALL_FUNCTION_1
classdefdeco1 ::= expr . classdefdeco2 CALL_FUNCTION_1
come_from_loops ::= \e_come_from_loops . COME_FROM_LOOP
come_from_opt ::= COME_FROM . 
come_froms ::= COME_FROM . 
come_froms ::= come_froms . COME_FROM
compare ::= compare_single . 
compare_chained ::= expr . compared_chained_middle ROT_TWO POP_TOP \e__come_froms
compare_chained ::= expr . compared_chained_middle ROT_TWO POP_TOP _come_froms
compare_chained37 ::= expr . compared_chained_middlea_37
compare_chained37 ::= expr . compared_chained_middlec_37
compare_chained37_false ::= expr . compare_chained_right_false_37
compare_chained37_false ::= expr . compared_chained_middle_false_37
compare_chained37_false ::= expr . compared_chained_middleb_false_37
compare_chained_right_false_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_righta_false_37 POP_TOP JUMP_BACK COME_FROM
compare_single ::= expr . expr COMPARE_OP
compare_single ::= expr expr . COMPARE_OP
compare_single ::= expr expr COMPARE_OP . 
compared_chained_middle ::= expr . DUP_TOP ROT_THREE COMPARE_OP JUMP_IF_FALSE_OR_POP compare_chained_right COME_FROM
compared_chained_middle ::= expr . DUP_TOP ROT_THREE COMPARE_OP JUMP_IF_FALSE_OR_POP compared_chained_middle COME_FROM
compared_chained_middle_false_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_rightb_false_37 POP_TOP _jump COME_FROM
compared_chained_middle_false_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_rightc_37 POP_TOP JUMP_FORWARD COME_FROM
compared_chained_middlea_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE
compared_chained_middlea_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_righta_37 COME_FROM POP_TOP COME_FROM
compared_chained_middleb_false_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_rightb_false_37 POP_TOP _jump COME_FROM
compared_chained_middlec_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_righta_37 POP_TOP
const_list ::= COLLECTION_START . add_consts BUILD_CONST_DICT
const_list ::= COLLECTION_START . add_consts BUILD_CONST_SET
const_list ::= COLLECTION_START \e_add_consts . BUILD_CONST_DICT
const_list ::= COLLECTION_START \e_add_consts . BUILD_CONST_SET
const_list ::= COLLECTION_START add_consts . BUILD_CONST_DICT
const_list ::= COLLECTION_START add_consts . BUILD_CONST_SET
const_list ::= COLLECTION_START add_consts BUILD_CONST_SET . 
continues ::= _stmts . lastl_stmt continue
continues ::= _stmts lastl_stmt . continue
continues ::= lastl_stmt . continue
dict ::= const_list . 
dict ::= expr . LOAD_CONST BUILD_CONST_KEY_MAP_1
dict ::= expr . expr LOAD_CONST BUILD_CONST_KEY_MAP_2
dict ::= expr . expr expr LOAD_CONST BUILD_CONST_KEY_MAP_3
dict ::= expr LOAD_CONST . BUILD_CONST_KEY_MAP_1
dict ::= expr expr . LOAD_CONST BUILD_CONST_KEY_MAP_2
dict ::= expr expr . expr LOAD_CONST BUILD_CONST_KEY_MAP_3
dict ::= expr expr LOAD_CONST . BUILD_CONST_KEY_MAP_2
dict ::= expr expr LOAD_CONST BUILD_CONST_KEY_MAP_2 . 
dict ::= expr expr expr . LOAD_CONST BUILD_CONST_KEY_MAP_3
dict ::= expr expr expr LOAD_CONST . BUILD_CONST_KEY_MAP_3
dict ::= kvlist_0 . 
else_suite ::= suite_stmts . 
except_ret38 ::= SETUP_FINALLY . expr ROT_FOUR POP_BLOCK POP_EXCEPT CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
except_ret38 ::= SETUP_FINALLY . expr ROT_FOUR POP_BLOCK POP_EXCEPT CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY suite_stmts_opt END_FINALLY
except_ret38 ::= SETUP_FINALLY expr . ROT_FOUR POP_BLOCK POP_EXCEPT CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
except_ret38 ::= SETUP_FINALLY expr . ROT_FOUR POP_BLOCK POP_EXCEPT CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY suite_stmts_opt END_FINALLY
except_return_value ::= expr . POP_BLOCK RETURN_VALUE
except_return_value ::= expr POP_BLOCK . RETURN_VALUE
expr ::= LOAD_CONST . 
expr ::= LOAD_FAST . 
expr ::= LOAD_GLOBAL . 
expr ::= LOAD_STR . 
expr ::= attribute . 
expr ::= attribute37 . 
expr ::= bin_op . 
expr ::= call . 
expr ::= call_kw36 . 
expr ::= compare . 
expr ::= const_list . 
expr ::= dict . 
expr ::= formatted_value1 . 
expr ::= get_iter . 
expr ::= joined_str . 
expr ::= or . 
expr ::= set_comp . 
expr ::= slice2 . 
expr ::= subscript . 
expr_jit ::= expr . JUMP_IF_TRUE
expr_jitop ::= expr . JUMP_IF_TRUE_OR_POP
expr_jitop ::= expr JUMP_IF_TRUE_OR_POP . 
expr_jt ::= expr . jmp_true
expr_pjit ::= expr . POP_JUMP_IF_TRUE
expr_pjit_come_from ::= expr . POP_JUMP_IF_TRUE COME_FROM
expr_stmt ::= expr . POP_TOP
for38 ::= expr . get_for_iter store for_block
for38 ::= expr . get_for_iter store for_block JUMP_BACK
for38 ::= expr . get_for_iter store for_block JUMP_BACK POP_BLOCK
for38 ::= expr . get_iter store for_block JUMP_BACK
for38 ::= expr get_for_iter . store for_block
for38 ::= expr get_for_iter . store for_block JUMP_BACK
for38 ::= expr get_for_iter . store for_block JUMP_BACK POP_BLOCK
for38 ::= expr get_for_iter store . for_block
for38 ::= expr get_for_iter store . for_block JUMP_BACK
for38 ::= expr get_for_iter store . for_block JUMP_BACK POP_BLOCK
for_block ::= \e__come_froms . l_stmts_opt _come_from_loops JUMP_BACK
for_block ::= \e__come_froms \e_l_stmts_opt . _come_from_loops JUMP_BACK
for_block ::= \e_l_stmts_opt . _come_froms JUMP_BACK
for_block ::= \e_l_stmts_opt . come_from_loops JUMP_BACK
for_block ::= \e_l_stmts_opt \e__come_froms . JUMP_BACK
for_block ::= \e_l_stmts_opt \e_come_from_loops . JUMP_BACK
forelselaststmt38 ::= expr . get_for_iter store for_block POP_BLOCK else_suitec
forelselaststmt38 ::= expr get_for_iter . store for_block POP_BLOCK else_suitec
forelselaststmt38 ::= expr get_for_iter store . for_block POP_BLOCK else_suitec
forelselaststmtl38 ::= expr . get_for_iter store for_block POP_BLOCK else_suitel
forelselaststmtl38 ::= expr get_for_iter . store for_block POP_BLOCK else_suitel
forelselaststmtl38 ::= expr get_for_iter store . for_block POP_BLOCK else_suitel
forelsestmt38 ::= expr . get_for_iter store for_block JUMP_BACK \e__come_froms else_suite
forelsestmt38 ::= expr . get_for_iter store for_block JUMP_BACK _come_froms else_suite
forelsestmt38 ::= expr . get_for_iter store for_block POP_BLOCK else_suite
forelsestmt38 ::= expr get_for_iter . store for_block JUMP_BACK \e__come_froms else_suite
forelsestmt38 ::= expr get_for_iter . store for_block JUMP_BACK _come_froms else_suite
forelsestmt38 ::= expr get_for_iter . store for_block POP_BLOCK else_suite
forelsestmt38 ::= expr get_for_iter store . for_block JUMP_BACK \e__come_froms else_suite
forelsestmt38 ::= expr get_for_iter store . for_block JUMP_BACK _come_froms else_suite
forelsestmt38 ::= expr get_for_iter store . for_block POP_BLOCK else_suite
formatted_value1 ::= expr . FORMAT_VALUE
formatted_value1 ::= expr FORMAT_VALUE . 
formatted_value_debug ::= LOAD_STR . formatted_value1 BUILD_STRING_2
formatted_value_debug ::= LOAD_STR . formatted_value2 BUILD_STRING_2
formatted_value_debug ::= LOAD_STR formatted_value1 . BUILD_STRING_2
get_for_iter ::= GET_ITER . _come_froms FOR_ITER
get_for_iter ::= GET_ITER \e__come_froms . FOR_ITER
get_for_iter ::= GET_ITER \e__come_froms FOR_ITER . 
get_iter ::= expr . GET_ITER
get_iter ::= expr GET_ITER . 
if_exp ::= expr . jmp_false expr jf_cf expr COME_FROM
if_exp ::= expr . jmp_false expr jump_absolute_else expr
if_exp ::= expr jmp_false . expr jf_cf expr COME_FROM
if_exp ::= expr jmp_false . expr jump_absolute_else expr
if_exp ::= expr jmp_false expr . jf_cf expr COME_FROM
if_exp ::= expr jmp_false expr . jump_absolute_else expr
if_exp37 ::= expr . expr jf_cfs expr COME_FROM
if_exp37 ::= expr expr . jf_cfs expr COME_FROM
if_exp_37b ::= expr . jmp_false expr POP_JUMP_IF_FALSE jump_forward_else expr
if_exp_37b ::= expr jmp_false . expr POP_JUMP_IF_FALSE jump_forward_else expr
if_exp_37b ::= expr jmp_false expr . POP_JUMP_IF_FALSE jump_forward_else expr
if_exp_lambda ::= expr . jmp_false expr return_if_lambda return_stmt_lambda LAMBDA_MARKER
if_exp_lambda ::= expr jmp_false . expr return_if_lambda return_stmt_lambda LAMBDA_MARKER
if_exp_lambda ::= expr jmp_false expr . return_if_lambda return_stmt_lambda LAMBDA_MARKER
if_exp_not ::= expr . jmp_true expr jump_forward_else expr COME_FROM
if_exp_not_lambda ::= expr . jmp_true expr return_if_lambda return_stmt_lambda LAMBDA_MARKER
if_exp_true ::= expr . JUMP_FORWARD expr COME_FROM
ifelsestmt ::= testexpr . c_stmts come_froms else_suite come_froms
ifelsestmt ::= testexpr . c_stmts_opt JUMP_FORWARD else_suite \e__come_froms
ifelsestmt ::= testexpr . c_stmts_opt JUMP_FORWARD else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr . c_stmts_opt JUMP_FORWARD else_suite _come_froms
ifelsestmt ::= testexpr . c_stmts_opt JUMP_FORWARD else_suite opt_come_from_except
ifelsestmt ::= testexpr . c_stmts_opt jf_cfs else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr . c_stmts_opt jf_cfs else_suite opt_come_from_except
ifelsestmt ::= testexpr . c_stmts_opt jump_forward_else else_suite \e__come_froms
ifelsestmt ::= testexpr . c_stmts_opt jump_forward_else else_suite _come_froms
ifelsestmt ::= testexpr . stmts jf_cfs \e_else_suite_opt \e_opt_come_from_except
ifelsestmt ::= testexpr . stmts jf_cfs \e_else_suite_opt opt_come_from_except
ifelsestmt ::= testexpr . stmts jf_cfs else_suite_opt \e_opt_come_from_except
ifelsestmt ::= testexpr . stmts jf_cfs else_suite_opt opt_come_from_except
ifelsestmt ::= testexpr \e_c_stmts_opt . JUMP_FORWARD else_suite \e__come_froms
ifelsestmt ::= testexpr \e_c_stmts_opt . JUMP_FORWARD else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr \e_c_stmts_opt . JUMP_FORWARD else_suite _come_froms
ifelsestmt ::= testexpr \e_c_stmts_opt . JUMP_FORWARD else_suite opt_come_from_except
ifelsestmt ::= testexpr \e_c_stmts_opt . jf_cfs else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr \e_c_stmts_opt . jf_cfs else_suite opt_come_from_except
ifelsestmt ::= testexpr \e_c_stmts_opt . jump_forward_else else_suite \e__come_froms
ifelsestmt ::= testexpr \e_c_stmts_opt . jump_forward_else else_suite _come_froms
ifelsestmt ::= testexpr c_stmts . come_froms else_suite come_froms
ifelsestmt ::= testexpr c_stmts come_froms . else_suite come_froms
ifelsestmt ::= testexpr c_stmts come_froms else_suite . come_froms
ifelsestmt ::= testexpr c_stmts come_froms else_suite come_froms . 
ifelsestmt ::= testexpr c_stmts_opt . JUMP_FORWARD else_suite \e__come_froms
ifelsestmt ::= testexpr c_stmts_opt . JUMP_FORWARD else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr c_stmts_opt . JUMP_FORWARD else_suite _come_froms
ifelsestmt ::= testexpr c_stmts_opt . JUMP_FORWARD else_suite opt_come_from_except
ifelsestmt ::= testexpr c_stmts_opt . jf_cfs else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr c_stmts_opt . jf_cfs else_suite opt_come_from_except
ifelsestmt ::= testexpr c_stmts_opt . jump_forward_else else_suite \e__come_froms
ifelsestmt ::= testexpr c_stmts_opt . jump_forward_else else_suite _come_froms
ifelsestmt ::= testexpr stmts . jf_cfs \e_else_suite_opt \e_opt_come_from_except
ifelsestmt ::= testexpr stmts . jf_cfs \e_else_suite_opt opt_come_from_except
ifelsestmt ::= testexpr stmts . jf_cfs else_suite_opt \e_opt_come_from_except
ifelsestmt ::= testexpr stmts . jf_cfs else_suite_opt opt_come_from_except
ifelsestmtc ::= testexpr . c_stmts_opt JUMP_ABSOLUTE else_suitec
ifelsestmtc ::= testexpr . c_stmts_opt JUMP_FORWARD else_suitec
ifelsestmtc ::= testexpr . c_stmts_opt jump_absolute_else else_suitec
ifelsestmtc ::= testexpr \e_c_stmts_opt . JUMP_ABSOLUTE else_suitec
ifelsestmtc ::= testexpr \e_c_stmts_opt . JUMP_FORWARD else_suitec
ifelsestmtc ::= testexpr \e_c_stmts_opt . jump_absolute_else else_suitec
ifelsestmtc ::= testexpr c_stmts_opt . JUMP_ABSOLUTE else_suitec
ifelsestmtc ::= testexpr c_stmts_opt . JUMP_FORWARD else_suitec
ifelsestmtc ::= testexpr c_stmts_opt . jump_absolute_else else_suitec
ifelsestmtl ::= testexpr . c_stmts cf_pt else_suite
ifelsestmtl ::= testexpr . c_stmts_opt cf_jf_else else_suitel
ifelsestmtl ::= testexpr . c_stmts_opt cf_jump_back else_suitel
ifelsestmtl ::= testexpr . c_stmts_opt jb_cfs else_suitel
ifelsestmtl ::= testexpr . c_stmts_opt jb_cfs else_suitel JUMP_BACK come_froms
ifelsestmtl ::= testexpr . c_stmts_opt jb_else else_suitel
ifelsestmtl ::= testexpr . c_stmts_opt jump_forward_else else_suitec
ifelsestmtl ::= testexpr \e_c_stmts_opt . cf_jf_else else_suitel
ifelsestmtl ::= testexpr \e_c_stmts_opt . cf_jump_back else_suitel
ifelsestmtl ::= testexpr \e_c_stmts_opt . jb_cfs else_suitel
ifelsestmtl ::= testexpr \e_c_stmts_opt . jb_cfs else_suitel JUMP_BACK come_froms
ifelsestmtl ::= testexpr \e_c_stmts_opt . jb_else else_suitel
ifelsestmtl ::= testexpr \e_c_stmts_opt . jump_forward_else else_suitec
ifelsestmtl ::= testexpr c_stmts . cf_pt else_suite
ifelsestmtl ::= testexpr c_stmts_opt . cf_jf_else else_suitel
ifelsestmtl ::= testexpr c_stmts_opt . cf_jump_back else_suitel
ifelsestmtl ::= testexpr c_stmts_opt . jb_cfs else_suitel
ifelsestmtl ::= testexpr c_stmts_opt . jb_cfs else_suitel JUMP_BACK come_froms
ifelsestmtl ::= testexpr c_stmts_opt . jb_else else_suitel
ifelsestmtl ::= testexpr c_stmts_opt . jump_forward_else else_suitec
ifelsestmtr ::= testexpr . return_if_stmts returns
iflaststmt ::= testexpr . c_stmts
iflaststmt ::= testexpr . c_stmts JUMP_ABSOLUTE
iflaststmt ::= testexpr . c_stmts_opt JUMP_FORWARD
iflaststmt ::= testexpr \e_c_stmts_opt . JUMP_FORWARD
iflaststmt ::= testexpr c_stmts . 
iflaststmt ::= testexpr c_stmts . JUMP_ABSOLUTE
iflaststmt ::= testexpr c_stmts_opt . JUMP_FORWARD
iflaststmtl ::= testexpr . c_stmts
iflaststmtl ::= testexpr . c_stmts JUMP_BACK
iflaststmtl ::= testexpr . c_stmts JUMP_BACK COME_FROM_LOOP
iflaststmtl ::= testexpr . c_stmts JUMP_BACK POP_BLOCK
iflaststmtl ::= testexpr c_stmts . 
iflaststmtl ::= testexpr c_stmts . JUMP_BACK
iflaststmtl ::= testexpr c_stmts . JUMP_BACK COME_FROM_LOOP
iflaststmtl ::= testexpr c_stmts . JUMP_BACK POP_BLOCK
ifpoplaststmtl ::= testexpr . POP_TOP \e_c_stmts_opt
ifpoplaststmtl ::= testexpr . POP_TOP c_stmts_opt
ifstmt ::= testexpr . _ifstmts_jump
ifstmt ::= testexpr _ifstmts_jump . 
ifstmtl ::= testexpr . _ifstmts_jumpl
ifstmtl ::= testexpr _ifstmts_jumpl . 
import ::= LOAD_CONST . LOAD_CONST alias
import_as37 ::= LOAD_CONST . LOAD_CONST importlist37 store POP_TOP
import_from ::= LOAD_CONST . LOAD_CONST IMPORT_NAME importlist POP_TOP
import_from ::= LOAD_CONST . LOAD_CONST importlist POP_TOP
import_from37 ::= LOAD_CONST . LOAD_CONST IMPORT_NAME_ATTR importlist37 POP_TOP
import_from_as37 ::= LOAD_CONST . LOAD_CONST import_from_attr37 store POP_TOP
import_from_star ::= LOAD_CONST . LOAD_CONST IMPORT_NAME IMPORT_STAR
import_from_star ::= LOAD_CONST . LOAD_CONST IMPORT_NAME_ATTR IMPORT_STAR
importmultiple ::= LOAD_CONST . LOAD_CONST alias imports_cont
jb_cfs ::= \e_come_from_opt . JUMP_BACK come_froms
jb_cfs ::= come_from_opt . JUMP_BACK come_froms
jmp_false ::= POP_JUMP_IF_FALSE . 
joined_str ::= expr . expr BUILD_STRING_2
joined_str ::= expr . expr expr expr BUILD_STRING_4
joined_str ::= expr . expr expr expr expr BUILD_STRING_5
joined_str ::= expr expr . BUILD_STRING_2
joined_str ::= expr expr . expr expr BUILD_STRING_4
joined_str ::= expr expr . expr expr expr BUILD_STRING_5
joined_str ::= expr expr BUILD_STRING_2 . 
joined_str ::= expr expr expr . expr BUILD_STRING_4
joined_str ::= expr expr expr . expr expr BUILD_STRING_5
joined_str ::= expr expr expr expr . BUILD_STRING_4
joined_str ::= expr expr expr expr . expr BUILD_STRING_5
joined_str ::= expr expr expr expr BUILD_STRING_4 . 
joined_str ::= expr expr expr expr expr . BUILD_STRING_5
joined_str ::= expr expr expr expr expr BUILD_STRING_5 . 
jump_absolute_else ::= come_froms . _jump COME_FROM
kvlist_0 ::= BUILD_MAP_0 . 
l_stmts ::= _stmts . 
l_stmts ::= _stmts . lastl_stmt
l_stmts ::= _stmts lastl_stmt . 
l_stmts ::= l_stmts . lstmt
l_stmts ::= l_stmts lstmt . 
l_stmts ::= lastl_stmt . 
l_stmts ::= lastl_stmt . come_froms l_stmts
l_stmts ::= lastl_stmt come_froms . l_stmts
l_stmts ::= lastl_stmt come_froms l_stmts . 
l_stmts ::= lstmt . 
l_stmts_opt ::= l_stmts . 
lambda_body ::= expr . LOAD_LAMBDA LOAD_STR MAKE_FUNCTION_4
lambda_body ::= expr . expr LOAD_LAMBDA LOAD_STR MAKE_FUNCTION_5
lambda_body ::= expr . expr LOAD_LAMBDA LOAD_STR MAKE_FUNCTION_6
lambda_body ::= expr expr . LOAD_LAMBDA LOAD_STR MAKE_FUNCTION_5
lambda_body ::= expr expr . LOAD_LAMBDA LOAD_STR MAKE_FUNCTION_6
lastc_stmt ::= iflaststmt . 
lastl_stmt ::= iflaststmtl . 
lc_setup_finally ::= LOAD_CONST . SETUP_FINALLY
lstmt ::= stmt . 
mkfunc ::= expr . LOAD_CODE LOAD_STR MAKE_FUNCTION_4
mkfunc ::= expr . expr LOAD_CODE LOAD_STR MAKE_FUNCTION_5
mkfunc ::= expr . expr LOAD_CODE LOAD_STR MAKE_FUNCTION_6
mkfunc ::= expr expr . LOAD_CODE LOAD_STR MAKE_FUNCTION_5
mkfunc ::= expr expr . LOAD_CODE LOAD_STR MAKE_FUNCTION_6
mkfuncdeco ::= expr . mkfuncdeco CALL_FUNCTION_1
mkfuncdeco ::= expr . mkfuncdeco0 CALL_FUNCTION_1
named_expr ::= expr . DUP_TOP store
or ::= expr_jitop . expr COME_FROM
or ::= expr_jitop expr . COME_FROM
or ::= expr_jitop expr COME_FROM . 
pop_ex_return ::= return_expr . ROT_FOUR POP_EXCEPT RETURN_VALUE
popb_return ::= return_expr . POP_BLOCK RETURN_VALUE
popb_return ::= return_expr POP_BLOCK . RETURN_VALUE
pos_arg ::= expr . 
raise_stmt1 ::= expr . RAISE_VARARGS_1
raise_stmt1 ::= expr RAISE_VARARGS_1 . 
ret_and ::= expr . JUMP_IF_FALSE_OR_POP return_expr_or_cond COME_FROM
ret_or ::= expr . JUMP_IF_TRUE_OR_POP return_expr_or_cond COME_FROM
return ::= return_expr . RETURN_END_IF
return ::= return_expr . RETURN_VALUE
return ::= return_expr . RETURN_VALUE COME_FROM
return ::= return_expr . discard_tops RETURN_VALUE
return_except ::= stmts . POP_BLOCK return
return_expr ::= expr . 
return_expr_lambda ::= return_expr . RETURN_VALUE_LAMBDA
return_expr_lambda ::= return_expr . RETURN_VALUE_LAMBDA LAMBDA_MARKER
return_if_stmt ::= return_expr . RETURN_END_IF
return_if_stmt ::= return_expr . RETURN_END_IF POP_BLOCK
return_if_stmts ::= _stmts . return_if_stmt \e__come_froms
return_if_stmts ::= _stmts . return_if_stmt _come_froms
returns ::= _stmts . return
returns ::= _stmts . return_if_stmt
returns_in_except ::= _stmts . except_return_value
set_comp ::= LOAD_SETCOMP . LOAD_STR MAKE_FUNCTION_0 expr GET_ITER CALL_FUNCTION_1
set_comp ::= LOAD_SETCOMP LOAD_STR . MAKE_FUNCTION_0 expr GET_ITER CALL_FUNCTION_1
set_comp ::= LOAD_SETCOMP LOAD_STR MAKE_FUNCTION_0 . expr GET_ITER CALL_FUNCTION_1
set_comp ::= LOAD_SETCOMP LOAD_STR MAKE_FUNCTION_0 expr . GET_ITER CALL_FUNCTION_1
set_comp ::= LOAD_SETCOMP LOAD_STR MAKE_FUNCTION_0 expr GET_ITER . CALL_FUNCTION_1
set_comp ::= LOAD_SETCOMP LOAD_STR MAKE_FUNCTION_0 expr GET_ITER CALL_FUNCTION_1 . 
sf_pb_call_returns ::= SETUP_FINALLY . POP_BLOCK CALL_FINALLY returns
slice2 ::= expr . expr BUILD_SLICE_2
slice2 ::= expr expr . BUILD_SLICE_2
slice2 ::= expr expr BUILD_SLICE_2 . 
sstmt ::= sstmt . RETURN_LAST
sstmt ::= stmt . 
stmt ::= assign . 
stmt ::= call_stmt . 
stmt ::= ifstmt . 
stmt ::= ifstmtl . 
stmt ::= raise_stmt1 . 
stmts ::= sstmt . 
stmts ::= stmts . sstmt
stmts ::= stmts sstmt . 
store ::= STORE_FAST . 
store ::= expr . STORE_ATTR
store_subscript ::= expr . expr STORE_SUBSCR
store_subscript ::= expr expr . STORE_SUBSCR
subscript ::= expr . expr BINARY_SUBSCR
subscript ::= expr expr . BINARY_SUBSCR
subscript ::= expr expr BINARY_SUBSCR . 
subscript2 ::= expr . expr DUP_TOP_TWO BINARY_SUBSCR
subscript2 ::= expr expr . DUP_TOP_TWO BINARY_SUBSCR
suite_stmts ::= _stmts . 
suite_stmts_opt ::= suite_stmts . 
testexpr ::= testfalse . 
testexpr_cf ::= testexpr . come_froms
testfalse ::= expr . jmp_false
testfalse ::= expr jmp_false . 
testfalse_not_and ::= expr . jmp_false expr jmp_true COME_FROM
testfalse_not_and ::= expr jmp_false . expr jmp_true COME_FROM
testfalse_not_and ::= expr jmp_false expr . jmp_true COME_FROM
testfalse_not_or ::= expr . jmp_false expr jmp_false COME_FROM
testfalse_not_or ::= expr jmp_false . expr jmp_false COME_FROM
testfalse_not_or ::= expr jmp_false expr . jmp_false COME_FROM
testfalsel ::= expr . jmp_true
testtrue ::= expr . jmp_true
try_elsestmtl38 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK except_handler38 COME_FROM else_suitel \e_opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK except_handler38 COME_FROM else_suitel opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK except_handler38 COME_FROM else_suitel \e_opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK except_handler38 COME_FROM else_suitel opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK except_handler38 COME_FROM else_suitel \e_opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK except_handler38 COME_FROM else_suitel opt_come_from_except
try_except ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK except_handler38
try_except ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK except_handler38
try_except ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK except_handler38
try_except38 ::= SETUP_FINALLY . POP_BLOCK POP_TOP \e_suite_stmts_opt except_handler38a
try_except38 ::= SETUP_FINALLY . POP_BLOCK POP_TOP suite_stmts_opt except_handler38a
try_except38 ::= SETUP_FINALLY . POP_BLOCK suite_stmts except_handler38b
try_except38r ::= SETUP_FINALLY . return_except except_handler38b
try_except38r2 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP \e_cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP \e_cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP \e_cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY \e_cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY \e_cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY \e_cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r4 ::= SETUP_FINALLY . returns_in_except COME_FROM_FINALLY except_cond1 return COME_FROM END_FINALLY
try_except_as ::= SETUP_FINALLY . POP_BLOCK suite_stmts except_handler_as END_FINALLY COME_FROM
try_except_as ::= SETUP_FINALLY . suite_stmts except_handler_as END_FINALLY COME_FROM
try_except_as ::= SETUP_FINALLY suite_stmts . except_handler_as END_FINALLY COME_FROM
try_except_ret38 ::= SETUP_FINALLY . returns except_ret38a
tryfinally36 ::= SETUP_FINALLY . returns COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinally36 ::= SETUP_FINALLY . returns COME_FROM_FINALLY suite_stmts
tryfinally36 ::= SETUP_FINALLY . returns COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinally38astmt ::= LOAD_CONST . SETUP_FINALLY \e_suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY POP_TOP \e_suite_stmts_opt END_FINALLY POP_TOP
tryfinally38astmt ::= LOAD_CONST . SETUP_FINALLY \e_suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY POP_TOP suite_stmts_opt END_FINALLY POP_TOP
tryfinally38astmt ::= LOAD_CONST . SETUP_FINALLY suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY POP_TOP \e_suite_stmts_opt END_FINALLY POP_TOP
tryfinally38astmt ::= LOAD_CONST . SETUP_FINALLY suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY POP_TOP suite_stmts_opt END_FINALLY POP_TOP
tryfinally38rstmt3 ::= SETUP_FINALLY . expr POP_BLOCK CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY ss_end_finally
tryfinally38rstmt3 ::= SETUP_FINALLY expr . POP_BLOCK CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY ss_end_finally
tryfinally38stmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY suite_stmts_opt END_FINALLY
tryfinally_return_stmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK LOAD_CONST COME_FROM_FINALLY
tryfinally_return_stmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY
tryfinally_return_stmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY
tryfinallystmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK LOAD_CONST COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK LOAD_CONST COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tuple ::= expr . expr BUILD_TUPLE_2
tuple ::= expr expr . BUILD_TUPLE_2
unary_not ::= expr . UNARY_NOT
unary_op ::= expr . unary_operator
while1stmt ::= \e__come_froms . l_stmts COME_FROM JUMP_BACK COME_FROM_LOOP
while1stmt ::= \e__come_froms l_stmts . COME_FROM JUMP_BACK COME_FROM_LOOP
while1stmt ::= \e__come_froms l_stmts COME_FROM . JUMP_BACK COME_FROM_LOOP
while1stmt ::= _come_froms . l_stmts COME_FROM JUMP_BACK COME_FROM_LOOP
while1stmt ::= _come_froms l_stmts . COME_FROM JUMP_BACK COME_FROM_LOOP
while1stmt ::= _come_froms l_stmts COME_FROM . JUMP_BACK COME_FROM_LOOP
whileTruestmt ::= \e__come_froms . l_stmts JUMP_BACK POP_BLOCK
whileTruestmt ::= \e__come_froms l_stmts . JUMP_BACK POP_BLOCK
whileTruestmt ::= _come_froms . l_stmts JUMP_BACK POP_BLOCK
whileTruestmt ::= _come_froms l_stmts . JUMP_BACK POP_BLOCK
whileTruestmt38 ::= \e__come_froms . l_stmts JUMP_BACK
whileTruestmt38 ::= \e__come_froms . l_stmts JUMP_BACK COME_FROM_EXCEPT_CLAUSE
whileTruestmt38 ::= \e__come_froms . pass JUMP_BACK
whileTruestmt38 ::= \e__come_froms \e_pass . JUMP_BACK
whileTruestmt38 ::= \e__come_froms l_stmts . JUMP_BACK
whileTruestmt38 ::= \e__come_froms l_stmts . JUMP_BACK COME_FROM_EXCEPT_CLAUSE
whileTruestmt38 ::= _come_froms . l_stmts JUMP_BACK
whileTruestmt38 ::= _come_froms . l_stmts JUMP_BACK COME_FROM_EXCEPT_CLAUSE
whileTruestmt38 ::= _come_froms . pass JUMP_BACK
whileTruestmt38 ::= _come_froms \e_pass . JUMP_BACK
whileTruestmt38 ::= _come_froms l_stmts . JUMP_BACK
whileTruestmt38 ::= _come_froms l_stmts . JUMP_BACK COME_FROM_EXCEPT_CLAUSE
whilestmt38 ::= \e__come_froms . testexpr \e_l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms . testexpr \e_l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms . testexpr \e_l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= \e__come_froms . testexpr l_stmts JUMP_BACK
whilestmt38 ::= \e__come_froms . testexpr l_stmts come_froms
whilestmt38 ::= \e__come_froms . testexpr l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms . testexpr l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms . testexpr l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= \e__come_froms . testexpr returns POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr . l_stmts JUMP_BACK
whilestmt38 ::= \e__come_froms testexpr . l_stmts come_froms
whilestmt38 ::= \e__come_froms testexpr . l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr . l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr . l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= \e__come_froms testexpr . returns POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr \e_l_stmts_opt . COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr \e_l_stmts_opt . JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr \e_l_stmts_opt . JUMP_BACK come_froms
whilestmt38 ::= \e__come_froms testexpr l_stmts . JUMP_BACK
whilestmt38 ::= \e__come_froms testexpr l_stmts . come_froms
whilestmt38 ::= \e__come_froms testexpr l_stmts come_froms . 
whilestmt38 ::= \e__come_froms testexpr l_stmts_opt . COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr l_stmts_opt . JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr l_stmts_opt . JUMP_BACK come_froms
whilestmt38 ::= \e__come_froms testexpr l_stmts_opt COME_FROM . JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms . testexpr \e_l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms . testexpr \e_l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms . testexpr \e_l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= _come_froms . testexpr l_stmts JUMP_BACK
whilestmt38 ::= _come_froms . testexpr l_stmts come_froms
whilestmt38 ::= _come_froms . testexpr l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms . testexpr l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms . testexpr l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= _come_froms . testexpr returns POP_BLOCK
whilestmt38 ::= _come_froms testexpr . l_stmts JUMP_BACK
whilestmt38 ::= _come_froms testexpr . l_stmts come_froms
whilestmt38 ::= _come_froms testexpr . l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr . l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr . l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= _come_froms testexpr . returns POP_BLOCK
whilestmt38 ::= _come_froms testexpr \e_l_stmts_opt . COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr \e_l_stmts_opt . JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr \e_l_stmts_opt . JUMP_BACK come_froms
whilestmt38 ::= _come_froms testexpr l_stmts . JUMP_BACK
whilestmt38 ::= _come_froms testexpr l_stmts . come_froms
whilestmt38 ::= _come_froms testexpr l_stmts come_froms . 
whilestmt38 ::= _come_froms testexpr l_stmts_opt . COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr l_stmts_opt . JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr l_stmts_opt . JUMP_BACK come_froms
whilestmt38 ::= _come_froms testexpr l_stmts_opt COME_FROM . JUMP_BACK POP_BLOCK
yield ::= expr . YIELD_VALUE
yield_from ::= expr . GET_YIELD_FROM_ITER LOAD_CONST YIELD_FROM
Instruction context:
   
 L. 181       252  LOAD_FAST                'data'
                 254  LOAD_STR                 'data'
                 256  BINARY_SUBSCR    
                 258  POP_BLOCK        
->               260  ROT_TWO          
                 262  POP_TOP          
                 264  RETURN_VALUE     
               266_0  COME_FROM_FINALLY    54  '54'

-- Stacks of completed symbols:
START ::= |- stmts . 
_come_froms ::= \e__come_froms . COME_FROM
_come_froms ::= \e__come_froms . COME_FROM_LOOP
_come_froms ::= \e__come_froms COME_FROM . 
_come_froms ::= _come_froms . COME_FROM
_come_froms ::= _come_froms . COME_FROM_LOOP
_ifstmts_jump ::= \e_c_stmts_opt . COME_FROM
_ifstmts_jump ::= \e_c_stmts_opt . ELSE
_ifstmts_jump ::= \e_c_stmts_opt . JUMP_ABSOLUTE JUMP_FORWARD \e__come_froms
_ifstmts_jump ::= \e_c_stmts_opt . JUMP_ABSOLUTE JUMP_FORWARD _come_froms
_ifstmts_jump ::= \e_c_stmts_opt . come_froms
_ifstmts_jump ::= c_stmts_opt . COME_FROM
_ifstmts_jump ::= c_stmts_opt . ELSE
_ifstmts_jump ::= c_stmts_opt . JUMP_ABSOLUTE JUMP_FORWARD \e__come_froms
_ifstmts_jump ::= c_stmts_opt . JUMP_ABSOLUTE JUMP_FORWARD _come_froms
_ifstmts_jump ::= c_stmts_opt . come_froms
_ifstmts_jump ::= c_stmts_opt COME_FROM . 
_ifstmts_jump ::= c_stmts_opt come_froms . 
_ifstmts_jumpl ::= _ifstmts_jump . 
_ifstmts_jumpl ::= c_stmts . JUMP_BACK
_stmts ::= _stmts . stmt
_stmts ::= _stmts stmt . 
_stmts ::= stmt . 
add_consts ::= \e_add_consts . ADD_VALUE
add_consts ::= \e_add_consts ADD_VALUE . 
add_consts ::= add_consts . ADD_VALUE
add_consts ::= add_consts ADD_VALUE . 
and ::= expr . JUMP_IF_FALSE_OR_POP expr \e_come_from_opt
and ::= expr . JUMP_IF_FALSE_OR_POP expr come_from_opt
and ::= expr . jifop_come_from expr
and ::= expr . jmp_false expr
and ::= expr . jmp_false expr COME_FROM
and ::= expr . jmp_false expr jmp_false
and ::= expr jmp_false . expr
and ::= expr jmp_false . expr COME_FROM
and ::= expr jmp_false . expr jmp_false
and ::= expr jmp_false expr . 
and ::= expr jmp_false expr . COME_FROM
and ::= expr jmp_false expr . jmp_false
and_not ::= expr . jmp_false expr POP_JUMP_IF_TRUE
and_not ::= expr jmp_false . expr POP_JUMP_IF_TRUE
and_not ::= expr jmp_false expr . POP_JUMP_IF_TRUE
assert2 ::= expr . jmp_true LOAD_GLOBAL expr CALL_FUNCTION_1 RAISE_VARARGS_1
assign ::= expr . DUP_TOP designList
assign ::= expr . store
assign ::= expr store . 
assign2 ::= expr . expr ROT_TWO store store
assign2 ::= expr expr . ROT_TWO store store
assign3 ::= expr . expr expr ROT_THREE ROT_TWO store store store
assign3 ::= expr expr . expr ROT_THREE ROT_TWO store store store
assign3 ::= expr expr expr . ROT_THREE ROT_TWO store store store
async_for_stmt38 ::= expr . async_for store for_block COME_FROM_FINALLY END_ASYNC_FOR
async_forelse_stmt38 ::= expr . GET_AITER SETUP_FINALLY GET_ANEXT LOAD_CONST YIELD_FROM POP_BLOCK store for_block COME_FROM_FINALLY END_ASYNC_FOR else_suite
attribute ::= expr . LOAD_ATTR
attribute ::= expr LOAD_ATTR . 
attribute37 ::= expr . LOAD_METHOD
attribute37 ::= expr LOAD_METHOD . 
aug_assign1 ::= expr . expr inplace_op ROT_THREE STORE_SUBSCR
aug_assign1 ::= expr . expr inplace_op store
aug_assign1 ::= expr expr . inplace_op ROT_THREE STORE_SUBSCR
aug_assign1 ::= expr expr . inplace_op store
aug_assign2 ::= expr . DUP_TOP LOAD_ATTR expr inplace_op ROT_TWO STORE_ATTR
await_expr ::= expr . GET_AWAITABLE LOAD_CONST YIELD_FROM
bin_op ::= expr . expr binary_operator
bin_op ::= expr expr . binary_operator
bin_op ::= expr expr binary_operator . 
binary_operator ::= BINARY_ADD . 
binary_operator ::= BINARY_AND . 
break ::= POP_BLOCK . BREAK_LOOP
break ::= POP_BLOCK . POP_TOP BREAK_LOOP
break ::= POP_TOP . BREAK_LOOP
c_stmts ::= _stmts . 
c_stmts ::= _stmts . lastc_stmt
c_stmts ::= _stmts lastc_stmt . 
c_stmts_opt ::= c_stmts . 
call ::= expr . CALL_METHOD_0
call ::= expr . pos_arg CALL_FUNCTION_1
call ::= expr . pos_arg CALL_METHOD_1
call ::= expr . pos_arg pos_arg CALL_FUNCTION_2
call ::= expr . pos_arg pos_arg CALL_METHOD_2
call ::= expr . pos_arg pos_arg pos_arg CALL_FUNCTION_3
call ::= expr . pos_arg pos_arg pos_arg CALL_METHOD_3
call ::= expr . pos_arg pos_arg pos_arg pos_arg CALL_METHOD_4
call ::= expr . pos_arg pos_arg pos_arg pos_arg pos_arg pos_arg CALL_METHOD_6
call ::= expr CALL_METHOD_0 . 
call ::= expr pos_arg . CALL_FUNCTION_1
call ::= expr pos_arg . CALL_METHOD_1
call ::= expr pos_arg . pos_arg CALL_FUNCTION_2
call ::= expr pos_arg . pos_arg CALL_METHOD_2
call ::= expr pos_arg . pos_arg pos_arg CALL_FUNCTION_3
call ::= expr pos_arg . pos_arg pos_arg CALL_METHOD_3
call ::= expr pos_arg . pos_arg pos_arg pos_arg CALL_METHOD_4
call ::= expr pos_arg . pos_arg pos_arg pos_arg pos_arg pos_arg CALL_METHOD_6
call ::= expr pos_arg CALL_FUNCTION_1 . 
call ::= expr pos_arg CALL_METHOD_1 . 
call ::= expr pos_arg pos_arg . CALL_FUNCTION_2
call ::= expr pos_arg pos_arg . CALL_METHOD_2
call ::= expr pos_arg pos_arg . pos_arg CALL_FUNCTION_3
call ::= expr pos_arg pos_arg . pos_arg CALL_METHOD_3
call ::= expr pos_arg pos_arg . pos_arg pos_arg CALL_METHOD_4
call ::= expr pos_arg pos_arg . pos_arg pos_arg pos_arg pos_arg CALL_METHOD_6
call ::= expr pos_arg pos_arg CALL_FUNCTION_2 . 
call ::= expr pos_arg pos_arg pos_arg . CALL_FUNCTION_3
call ::= expr pos_arg pos_arg pos_arg . CALL_METHOD_3
call ::= expr pos_arg pos_arg pos_arg . pos_arg CALL_METHOD_4
call ::= expr pos_arg pos_arg pos_arg . pos_arg pos_arg pos_arg CALL_METHOD_6
call ::= expr pos_arg pos_arg pos_arg CALL_METHOD_3 . 
call ::= expr pos_arg pos_arg pos_arg pos_arg . CALL_METHOD_4
call ::= expr pos_arg pos_arg pos_arg pos_arg . pos_arg pos_arg CALL_METHOD_6
call ::= expr pos_arg pos_arg pos_arg pos_arg pos_arg . pos_arg CALL_METHOD_6
call ::= expr pos_arg pos_arg pos_arg pos_arg pos_arg pos_arg . CALL_METHOD_6
call_kw36 ::= expr . expr expr LOAD_CONST CALL_FUNCTION_KW_2
call_kw36 ::= expr expr . expr LOAD_CONST CALL_FUNCTION_KW_2
call_kw36 ::= expr expr expr . LOAD_CONST CALL_FUNCTION_KW_2
call_kw36 ::= expr expr expr LOAD_CONST . CALL_FUNCTION_KW_2
call_kw36 ::= expr expr expr LOAD_CONST CALL_FUNCTION_KW_2 . 
call_stmt ::= call . 
call_stmt ::= expr . POP_TOP
call_stmt ::= expr POP_TOP . 
cf_jf_else ::= come_froms . JUMP_FORWARD ELSE
cf_jump_back ::= COME_FROM . JUMP_BACK
cf_pt ::= COME_FROM . POP_TOP
classdefdeco1 ::= expr . classdefdeco1 CALL_FUNCTION_1
classdefdeco1 ::= expr . classdefdeco2 CALL_FUNCTION_1
come_from_loops ::= \e_come_from_loops . COME_FROM_LOOP
come_from_opt ::= COME_FROM . 
come_froms ::= COME_FROM . 
come_froms ::= come_froms . COME_FROM
compare ::= compare_single . 
compare_chained ::= expr . compared_chained_middle ROT_TWO POP_TOP \e__come_froms
compare_chained ::= expr . compared_chained_middle ROT_TWO POP_TOP _come_froms
compare_chained37 ::= expr . compared_chained_middlea_37
compare_chained37 ::= expr . compared_chained_middlec_37
compare_chained37_false ::= expr . compare_chained_right_false_37
compare_chained37_false ::= expr . compared_chained_middle_false_37
compare_chained37_false ::= expr . compared_chained_middleb_false_37
compare_chained_right_false_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_righta_false_37 POP_TOP JUMP_BACK COME_FROM
compare_single ::= expr . expr COMPARE_OP
compare_single ::= expr expr . COMPARE_OP
compare_single ::= expr expr COMPARE_OP . 
compared_chained_middle ::= expr . DUP_TOP ROT_THREE COMPARE_OP JUMP_IF_FALSE_OR_POP compare_chained_right COME_FROM
compared_chained_middle ::= expr . DUP_TOP ROT_THREE COMPARE_OP JUMP_IF_FALSE_OR_POP compared_chained_middle COME_FROM
compared_chained_middle_false_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_rightb_false_37 POP_TOP _jump COME_FROM
compared_chained_middle_false_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_rightc_37 POP_TOP JUMP_FORWARD COME_FROM
compared_chained_middlea_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE
compared_chained_middlea_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_righta_37 COME_FROM POP_TOP COME_FROM
compared_chained_middleb_false_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_rightb_false_37 POP_TOP _jump COME_FROM
compared_chained_middlec_37 ::= expr . DUP_TOP ROT_THREE COMPARE_OP POP_JUMP_IF_FALSE compare_chained_righta_37 POP_TOP
const_list ::= COLLECTION_START . add_consts BUILD_CONST_DICT
const_list ::= COLLECTION_START . add_consts BUILD_CONST_SET
const_list ::= COLLECTION_START \e_add_consts . BUILD_CONST_DICT
const_list ::= COLLECTION_START \e_add_consts . BUILD_CONST_SET
const_list ::= COLLECTION_START add_consts . BUILD_CONST_DICT
const_list ::= COLLECTION_START add_consts . BUILD_CONST_SET
const_list ::= COLLECTION_START add_consts BUILD_CONST_SET . 
continues ::= _stmts . lastl_stmt continue
continues ::= _stmts lastl_stmt . continue
continues ::= lastl_stmt . continue
dict ::= const_list . 
dict ::= expr . LOAD_CONST BUILD_CONST_KEY_MAP_1
dict ::= expr . expr LOAD_CONST BUILD_CONST_KEY_MAP_2
dict ::= expr . expr expr LOAD_CONST BUILD_CONST_KEY_MAP_3
dict ::= expr LOAD_CONST . BUILD_CONST_KEY_MAP_1
dict ::= expr expr . LOAD_CONST BUILD_CONST_KEY_MAP_2
dict ::= expr expr . expr LOAD_CONST BUILD_CONST_KEY_MAP_3
dict ::= expr expr LOAD_CONST . BUILD_CONST_KEY_MAP_2
dict ::= expr expr LOAD_CONST BUILD_CONST_KEY_MAP_2 . 
dict ::= expr expr expr . LOAD_CONST BUILD_CONST_KEY_MAP_3
dict ::= expr expr expr LOAD_CONST . BUILD_CONST_KEY_MAP_3
dict ::= kvlist_0 . 
else_suite ::= suite_stmts . 
except_cond1 ::= DUP_TOP . expr COMPARE_OP jmp_false POP_TOP POP_TOP POP_TOP
except_cond1 ::= DUP_TOP . expr COMPARE_OP jmp_false POP_TOP POP_TOP POP_TOP POP_EXCEPT
except_cond1 ::= DUP_TOP expr . COMPARE_OP jmp_false POP_TOP POP_TOP POP_TOP
except_cond1 ::= DUP_TOP expr . COMPARE_OP jmp_false POP_TOP POP_TOP POP_TOP POP_EXCEPT
except_cond1 ::= DUP_TOP expr COMPARE_OP . jmp_false POP_TOP POP_TOP POP_TOP
except_cond1 ::= DUP_TOP expr COMPARE_OP . jmp_false POP_TOP POP_TOP POP_TOP POP_EXCEPT
except_cond1 ::= DUP_TOP expr COMPARE_OP jmp_false . POP_TOP POP_TOP POP_TOP
except_cond1 ::= DUP_TOP expr COMPARE_OP jmp_false . POP_TOP POP_TOP POP_TOP POP_EXCEPT
except_cond1 ::= DUP_TOP expr COMPARE_OP jmp_false POP_TOP . POP_TOP POP_TOP
except_cond1 ::= DUP_TOP expr COMPARE_OP jmp_false POP_TOP . POP_TOP POP_TOP POP_EXCEPT
except_ret38 ::= SETUP_FINALLY . expr ROT_FOUR POP_BLOCK POP_EXCEPT CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
except_ret38 ::= SETUP_FINALLY . expr ROT_FOUR POP_BLOCK POP_EXCEPT CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY suite_stmts_opt END_FINALLY
except_ret38 ::= SETUP_FINALLY expr . ROT_FOUR POP_BLOCK POP_EXCEPT CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
except_ret38 ::= SETUP_FINALLY expr . ROT_FOUR POP_BLOCK POP_EXCEPT CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY suite_stmts_opt END_FINALLY
except_return_value ::= POP_BLOCK . return
except_return_value ::= POP_BLOCK return . 
except_return_value ::= expr . POP_BLOCK RETURN_VALUE
except_return_value ::= expr POP_BLOCK . RETURN_VALUE
expr ::= LOAD_CONST . 
expr ::= LOAD_FAST . 
expr ::= LOAD_GLOBAL . 
expr ::= LOAD_STR . 
expr ::= attribute . 
expr ::= attribute37 . 
expr ::= bin_op . 
expr ::= call . 
expr ::= call_kw36 . 
expr ::= compare . 
expr ::= const_list . 
expr ::= dict . 
expr ::= formatted_value1 . 
expr ::= get_iter . 
expr ::= joined_str . 
expr ::= or . 
expr ::= set_comp . 
expr ::= slice2 . 
expr ::= subscript . 
expr_jit ::= expr . JUMP_IF_TRUE
expr_jitop ::= expr . JUMP_IF_TRUE_OR_POP
expr_jitop ::= expr JUMP_IF_TRUE_OR_POP . 
expr_jt ::= expr . jmp_true
expr_pjit ::= expr . POP_JUMP_IF_TRUE
expr_pjit_come_from ::= expr . POP_JUMP_IF_TRUE COME_FROM
expr_stmt ::= expr . POP_TOP
expr_stmt ::= expr POP_TOP . 
for38 ::= expr . get_for_iter store for_block
for38 ::= expr . get_for_iter store for_block JUMP_BACK
for38 ::= expr . get_for_iter store for_block JUMP_BACK POP_BLOCK
for38 ::= expr . get_iter store for_block JUMP_BACK
for38 ::= expr get_for_iter . store for_block
for38 ::= expr get_for_iter . store for_block JUMP_BACK
for38 ::= expr get_for_iter . store for_block JUMP_BACK POP_BLOCK
for38 ::= expr get_for_iter store . for_block
for38 ::= expr get_for_iter store . for_block JUMP_BACK
for38 ::= expr get_for_iter store . for_block JUMP_BACK POP_BLOCK
for_block ::= \e__come_froms . l_stmts_opt _come_from_loops JUMP_BACK
for_block ::= \e__come_froms \e_l_stmts_opt . _come_from_loops JUMP_BACK
for_block ::= \e_l_stmts_opt . _come_froms JUMP_BACK
for_block ::= \e_l_stmts_opt . come_from_loops JUMP_BACK
for_block ::= \e_l_stmts_opt \e__come_froms . JUMP_BACK
for_block ::= \e_l_stmts_opt \e_come_from_loops . JUMP_BACK
forelselaststmt38 ::= expr . get_for_iter store for_block POP_BLOCK else_suitec
forelselaststmt38 ::= expr get_for_iter . store for_block POP_BLOCK else_suitec
forelselaststmt38 ::= expr get_for_iter store . for_block POP_BLOCK else_suitec
forelselaststmtl38 ::= expr . get_for_iter store for_block POP_BLOCK else_suitel
forelselaststmtl38 ::= expr get_for_iter . store for_block POP_BLOCK else_suitel
forelselaststmtl38 ::= expr get_for_iter store . for_block POP_BLOCK else_suitel
forelsestmt38 ::= expr . get_for_iter store for_block JUMP_BACK \e__come_froms else_suite
forelsestmt38 ::= expr . get_for_iter store for_block JUMP_BACK _come_froms else_suite
forelsestmt38 ::= expr . get_for_iter store for_block POP_BLOCK else_suite
forelsestmt38 ::= expr get_for_iter . store for_block JUMP_BACK \e__come_froms else_suite
forelsestmt38 ::= expr get_for_iter . store for_block JUMP_BACK _come_froms else_suite
forelsestmt38 ::= expr get_for_iter . store for_block POP_BLOCK else_suite
forelsestmt38 ::= expr get_for_iter store . for_block JUMP_BACK \e__come_froms else_suite
forelsestmt38 ::= expr get_for_iter store . for_block JUMP_BACK _come_froms else_suite
forelsestmt38 ::= expr get_for_iter store . for_block POP_BLOCK else_suite
formatted_value1 ::= expr . FORMAT_VALUE
formatted_value1 ::= expr FORMAT_VALUE . 
formatted_value_debug ::= LOAD_STR . formatted_value1 BUILD_STRING_2
formatted_value_debug ::= LOAD_STR . formatted_value2 BUILD_STRING_2
formatted_value_debug ::= LOAD_STR formatted_value1 . BUILD_STRING_2
get_for_iter ::= GET_ITER . _come_froms FOR_ITER
get_for_iter ::= GET_ITER \e__come_froms . FOR_ITER
get_for_iter ::= GET_ITER \e__come_froms FOR_ITER . 
get_iter ::= expr . GET_ITER
get_iter ::= expr GET_ITER . 
if_exp ::= expr . jmp_false expr jf_cf expr COME_FROM
if_exp ::= expr . jmp_false expr jump_absolute_else expr
if_exp ::= expr jmp_false . expr jf_cf expr COME_FROM
if_exp ::= expr jmp_false . expr jump_absolute_else expr
if_exp ::= expr jmp_false expr . jf_cf expr COME_FROM
if_exp ::= expr jmp_false expr . jump_absolute_else expr
if_exp37 ::= expr . expr jf_cfs expr COME_FROM
if_exp37 ::= expr expr . jf_cfs expr COME_FROM
if_exp_37b ::= expr . jmp_false expr POP_JUMP_IF_FALSE jump_forward_else expr
if_exp_37b ::= expr jmp_false . expr POP_JUMP_IF_FALSE jump_forward_else expr
if_exp_37b ::= expr jmp_false expr . POP_JUMP_IF_FALSE jump_forward_else expr
if_exp_lambda ::= expr . jmp_false expr return_if_lambda return_stmt_lambda LAMBDA_MARKER
if_exp_lambda ::= expr jmp_false . expr return_if_lambda return_stmt_lambda LAMBDA_MARKER
if_exp_lambda ::= expr jmp_false expr . return_if_lambda return_stmt_lambda LAMBDA_MARKER
if_exp_not ::= expr . jmp_true expr jump_forward_else expr COME_FROM
if_exp_not_lambda ::= expr . jmp_true expr return_if_lambda return_stmt_lambda LAMBDA_MARKER
if_exp_true ::= expr . JUMP_FORWARD expr COME_FROM
ifelsestmt ::= testexpr . c_stmts come_froms else_suite come_froms
ifelsestmt ::= testexpr . c_stmts_opt JUMP_FORWARD else_suite \e__come_froms
ifelsestmt ::= testexpr . c_stmts_opt JUMP_FORWARD else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr . c_stmts_opt JUMP_FORWARD else_suite _come_froms
ifelsestmt ::= testexpr . c_stmts_opt JUMP_FORWARD else_suite opt_come_from_except
ifelsestmt ::= testexpr . c_stmts_opt jf_cfs else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr . c_stmts_opt jf_cfs else_suite opt_come_from_except
ifelsestmt ::= testexpr . c_stmts_opt jump_forward_else else_suite \e__come_froms
ifelsestmt ::= testexpr . c_stmts_opt jump_forward_else else_suite _come_froms
ifelsestmt ::= testexpr . stmts jf_cfs \e_else_suite_opt \e_opt_come_from_except
ifelsestmt ::= testexpr . stmts jf_cfs \e_else_suite_opt opt_come_from_except
ifelsestmt ::= testexpr . stmts jf_cfs else_suite_opt \e_opt_come_from_except
ifelsestmt ::= testexpr . stmts jf_cfs else_suite_opt opt_come_from_except
ifelsestmt ::= testexpr \e_c_stmts_opt . JUMP_FORWARD else_suite \e__come_froms
ifelsestmt ::= testexpr \e_c_stmts_opt . JUMP_FORWARD else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr \e_c_stmts_opt . JUMP_FORWARD else_suite _come_froms
ifelsestmt ::= testexpr \e_c_stmts_opt . JUMP_FORWARD else_suite opt_come_from_except
ifelsestmt ::= testexpr \e_c_stmts_opt . jf_cfs else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr \e_c_stmts_opt . jf_cfs else_suite opt_come_from_except
ifelsestmt ::= testexpr \e_c_stmts_opt . jump_forward_else else_suite \e__come_froms
ifelsestmt ::= testexpr \e_c_stmts_opt . jump_forward_else else_suite _come_froms
ifelsestmt ::= testexpr c_stmts . come_froms else_suite come_froms
ifelsestmt ::= testexpr c_stmts come_froms . else_suite come_froms
ifelsestmt ::= testexpr c_stmts come_froms else_suite . come_froms
ifelsestmt ::= testexpr c_stmts come_froms else_suite come_froms . 
ifelsestmt ::= testexpr c_stmts_opt . JUMP_FORWARD else_suite \e__come_froms
ifelsestmt ::= testexpr c_stmts_opt . JUMP_FORWARD else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr c_stmts_opt . JUMP_FORWARD else_suite _come_froms
ifelsestmt ::= testexpr c_stmts_opt . JUMP_FORWARD else_suite opt_come_from_except
ifelsestmt ::= testexpr c_stmts_opt . jf_cfs else_suite \e_opt_come_from_except
ifelsestmt ::= testexpr c_stmts_opt . jf_cfs else_suite opt_come_from_except
ifelsestmt ::= testexpr c_stmts_opt . jump_forward_else else_suite \e__come_froms
ifelsestmt ::= testexpr c_stmts_opt . jump_forward_else else_suite _come_froms
ifelsestmt ::= testexpr stmts . jf_cfs \e_else_suite_opt \e_opt_come_from_except
ifelsestmt ::= testexpr stmts . jf_cfs \e_else_suite_opt opt_come_from_except
ifelsestmt ::= testexpr stmts . jf_cfs else_suite_opt \e_opt_come_from_except
ifelsestmt ::= testexpr stmts . jf_cfs else_suite_opt opt_come_from_except
ifelsestmtc ::= testexpr . c_stmts_opt JUMP_ABSOLUTE else_suitec
ifelsestmtc ::= testexpr . c_stmts_opt JUMP_FORWARD else_suitec
ifelsestmtc ::= testexpr . c_stmts_opt jump_absolute_else else_suitec
ifelsestmtc ::= testexpr \e_c_stmts_opt . JUMP_ABSOLUTE else_suitec
ifelsestmtc ::= testexpr \e_c_stmts_opt . JUMP_FORWARD else_suitec
ifelsestmtc ::= testexpr \e_c_stmts_opt . jump_absolute_else else_suitec
ifelsestmtc ::= testexpr c_stmts_opt . JUMP_ABSOLUTE else_suitec
ifelsestmtc ::= testexpr c_stmts_opt . JUMP_FORWARD else_suitec
ifelsestmtc ::= testexpr c_stmts_opt . jump_absolute_else else_suitec
ifelsestmtl ::= testexpr . c_stmts cf_pt else_suite
ifelsestmtl ::= testexpr . c_stmts_opt cf_jf_else else_suitel
ifelsestmtl ::= testexpr . c_stmts_opt cf_jump_back else_suitel
ifelsestmtl ::= testexpr . c_stmts_opt jb_cfs else_suitel
ifelsestmtl ::= testexpr . c_stmts_opt jb_cfs else_suitel JUMP_BACK come_froms
ifelsestmtl ::= testexpr . c_stmts_opt jb_else else_suitel
ifelsestmtl ::= testexpr . c_stmts_opt jump_forward_else else_suitec
ifelsestmtl ::= testexpr \e_c_stmts_opt . cf_jf_else else_suitel
ifelsestmtl ::= testexpr \e_c_stmts_opt . cf_jump_back else_suitel
ifelsestmtl ::= testexpr \e_c_stmts_opt . jb_cfs else_suitel
ifelsestmtl ::= testexpr \e_c_stmts_opt . jb_cfs else_suitel JUMP_BACK come_froms
ifelsestmtl ::= testexpr \e_c_stmts_opt . jb_else else_suitel
ifelsestmtl ::= testexpr \e_c_stmts_opt . jump_forward_else else_suitec
ifelsestmtl ::= testexpr c_stmts . cf_pt else_suite
ifelsestmtl ::= testexpr c_stmts_opt . cf_jf_else else_suitel
ifelsestmtl ::= testexpr c_stmts_opt . cf_jump_back else_suitel
ifelsestmtl ::= testexpr c_stmts_opt . jb_cfs else_suitel
ifelsestmtl ::= testexpr c_stmts_opt . jb_cfs else_suitel JUMP_BACK come_froms
ifelsestmtl ::= testexpr c_stmts_opt . jb_else else_suitel
ifelsestmtl ::= testexpr c_stmts_opt . jump_forward_else else_suitec
ifelsestmtr ::= testexpr . return_if_stmts returns
iflaststmt ::= testexpr . c_stmts
iflaststmt ::= testexpr . c_stmts JUMP_ABSOLUTE
iflaststmt ::= testexpr . c_stmts_opt JUMP_FORWARD
iflaststmt ::= testexpr \e_c_stmts_opt . JUMP_FORWARD
iflaststmt ::= testexpr c_stmts . 
iflaststmt ::= testexpr c_stmts . JUMP_ABSOLUTE
iflaststmt ::= testexpr c_stmts_opt . JUMP_FORWARD
iflaststmtl ::= testexpr . c_stmts
iflaststmtl ::= testexpr . c_stmts JUMP_BACK
iflaststmtl ::= testexpr . c_stmts JUMP_BACK COME_FROM_LOOP
iflaststmtl ::= testexpr . c_stmts JUMP_BACK POP_BLOCK
iflaststmtl ::= testexpr c_stmts . 
iflaststmtl ::= testexpr c_stmts . JUMP_BACK
iflaststmtl ::= testexpr c_stmts . JUMP_BACK COME_FROM_LOOP
iflaststmtl ::= testexpr c_stmts . JUMP_BACK POP_BLOCK
ifpoplaststmtl ::= testexpr . POP_TOP \e_c_stmts_opt
ifpoplaststmtl ::= testexpr . POP_TOP c_stmts_opt
ifstmt ::= testexpr . _ifstmts_jump
ifstmt ::= testexpr _ifstmts_jump . 
ifstmtl ::= testexpr . _ifstmts_jumpl
ifstmtl ::= testexpr _ifstmts_jumpl . 
import ::= LOAD_CONST . LOAD_CONST alias
import_as37 ::= LOAD_CONST . LOAD_CONST importlist37 store POP_TOP
import_from ::= LOAD_CONST . LOAD_CONST IMPORT_NAME importlist POP_TOP
import_from ::= LOAD_CONST . LOAD_CONST importlist POP_TOP
import_from37 ::= LOAD_CONST . LOAD_CONST IMPORT_NAME_ATTR importlist37 POP_TOP
import_from_as37 ::= LOAD_CONST . LOAD_CONST import_from_attr37 store POP_TOP
import_from_star ::= LOAD_CONST . LOAD_CONST IMPORT_NAME IMPORT_STAR
import_from_star ::= LOAD_CONST . LOAD_CONST IMPORT_NAME_ATTR IMPORT_STAR
importmultiple ::= LOAD_CONST . LOAD_CONST alias imports_cont
jb_cfs ::= \e_come_from_opt . JUMP_BACK come_froms
jb_cfs ::= come_from_opt . JUMP_BACK come_froms
jmp_false ::= POP_JUMP_IF_FALSE . 
joined_str ::= expr . expr BUILD_STRING_2
joined_str ::= expr . expr expr expr BUILD_STRING_4
joined_str ::= expr . expr expr expr expr BUILD_STRING_5
joined_str ::= expr expr . BUILD_STRING_2
joined_str ::= expr expr . expr expr BUILD_STRING_4
joined_str ::= expr expr . expr expr expr BUILD_STRING_5
joined_str ::= expr expr BUILD_STRING_2 . 
joined_str ::= expr expr expr . expr BUILD_STRING_4
joined_str ::= expr expr expr . expr expr BUILD_STRING_5
joined_str ::= expr expr expr expr . BUILD_STRING_4
joined_str ::= expr expr expr expr . expr BUILD_STRING_5
joined_str ::= expr expr expr expr BUILD_STRING_4 . 
joined_str ::= expr expr expr expr expr . BUILD_STRING_5
joined_str ::= expr expr expr expr expr BUILD_STRING_5 . 
jump_absolute_else ::= come_froms . _jump COME_FROM
kvlist_0 ::= BUILD_MAP_0 . 
l_stmts ::= _stmts . 
l_stmts ::= _stmts . lastl_stmt
l_stmts ::= _stmts lastl_stmt . 
l_stmts ::= l_stmts . lstmt
l_stmts ::= l_stmts lstmt . 
l_stmts ::= lastl_stmt . 
l_stmts ::= lastl_stmt . come_froms l_stmts
l_stmts ::= lastl_stmt come_froms . l_stmts
l_stmts ::= lastl_stmt come_froms l_stmts . 
l_stmts ::= lstmt . 
l_stmts ::= returns . 
l_stmts_opt ::= l_stmts . 
lambda_body ::= expr . LOAD_LAMBDA LOAD_STR MAKE_FUNCTION_4
lambda_body ::= expr . expr LOAD_LAMBDA LOAD_STR MAKE_FUNCTION_5
lambda_body ::= expr . expr LOAD_LAMBDA LOAD_STR MAKE_FUNCTION_6
lambda_body ::= expr expr . LOAD_LAMBDA LOAD_STR MAKE_FUNCTION_5
lambda_body ::= expr expr . LOAD_LAMBDA LOAD_STR MAKE_FUNCTION_6
lastc_stmt ::= iflaststmt . 
lastl_stmt ::= iflaststmtl . 
lc_setup_finally ::= LOAD_CONST . SETUP_FINALLY
lstmt ::= stmt . 
mkfunc ::= expr . LOAD_CODE LOAD_STR MAKE_FUNCTION_4
mkfunc ::= expr . expr LOAD_CODE LOAD_STR MAKE_FUNCTION_5
mkfunc ::= expr . expr LOAD_CODE LOAD_STR MAKE_FUNCTION_6
mkfunc ::= expr expr . LOAD_CODE LOAD_STR MAKE_FUNCTION_5
mkfunc ::= expr expr . LOAD_CODE LOAD_STR MAKE_FUNCTION_6
mkfuncdeco ::= expr . mkfuncdeco CALL_FUNCTION_1
mkfuncdeco ::= expr . mkfuncdeco0 CALL_FUNCTION_1
named_expr ::= expr . DUP_TOP store
or ::= expr_jitop . expr COME_FROM
or ::= expr_jitop expr . COME_FROM
or ::= expr_jitop expr COME_FROM . 
pop_ex_return ::= return_expr . ROT_FOUR POP_EXCEPT RETURN_VALUE
pop_return ::= POP_TOP . return_expr RETURN_VALUE
popb_return ::= return_expr . POP_BLOCK RETURN_VALUE
popb_return ::= return_expr POP_BLOCK . RETURN_VALUE
pos_arg ::= expr . 
raise_stmt1 ::= expr . RAISE_VARARGS_1
raise_stmt1 ::= expr RAISE_VARARGS_1 . 
ret_and ::= expr . JUMP_IF_FALSE_OR_POP return_expr_or_cond COME_FROM
ret_or ::= expr . JUMP_IF_TRUE_OR_POP return_expr_or_cond COME_FROM
return ::= return_expr . RETURN_END_IF
return ::= return_expr . RETURN_VALUE
return ::= return_expr . RETURN_VALUE COME_FROM
return ::= return_expr . discard_tops RETURN_VALUE
return ::= return_expr RETURN_VALUE . 
return ::= return_expr RETURN_VALUE . COME_FROM
return_except ::= stmts . POP_BLOCK return
return_except ::= stmts POP_BLOCK . return
return_except ::= stmts POP_BLOCK return . 
return_expr ::= expr . 
return_expr_lambda ::= return_expr . RETURN_VALUE_LAMBDA
return_expr_lambda ::= return_expr . RETURN_VALUE_LAMBDA LAMBDA_MARKER
return_if_stmt ::= return_expr . RETURN_END_IF
return_if_stmt ::= return_expr . RETURN_END_IF POP_BLOCK
return_if_stmts ::= _stmts . return_if_stmt \e__come_froms
return_if_stmts ::= _stmts . return_if_stmt _come_froms
returns ::= _stmts . return
returns ::= _stmts . return_if_stmt
returns ::= return . 
returns_in_except ::= _stmts . except_return_value
returns_in_except ::= _stmts except_return_value . 
set_comp ::= LOAD_SETCOMP . LOAD_STR MAKE_FUNCTION_0 expr GET_ITER CALL_FUNCTION_1
set_comp ::= LOAD_SETCOMP LOAD_STR . MAKE_FUNCTION_0 expr GET_ITER CALL_FUNCTION_1
set_comp ::= LOAD_SETCOMP LOAD_STR MAKE_FUNCTION_0 . expr GET_ITER CALL_FUNCTION_1
set_comp ::= LOAD_SETCOMP LOAD_STR MAKE_FUNCTION_0 expr . GET_ITER CALL_FUNCTION_1
set_comp ::= LOAD_SETCOMP LOAD_STR MAKE_FUNCTION_0 expr GET_ITER . CALL_FUNCTION_1
set_comp ::= LOAD_SETCOMP LOAD_STR MAKE_FUNCTION_0 expr GET_ITER CALL_FUNCTION_1 . 
sf_pb_call_returns ::= SETUP_FINALLY . POP_BLOCK CALL_FINALLY returns
slice2 ::= expr . expr BUILD_SLICE_2
slice2 ::= expr expr . BUILD_SLICE_2
slice2 ::= expr expr BUILD_SLICE_2 . 
sstmt ::= return . RETURN_LAST
sstmt ::= return RETURN_LAST . 
sstmt ::= sstmt . RETURN_LAST
sstmt ::= sstmt RETURN_LAST . 
sstmt ::= stmt . 
stmt ::= assign . 
stmt ::= call_stmt . 
stmt ::= expr_stmt . 
stmt ::= ifstmt . 
stmt ::= ifstmtl . 
stmt ::= raise_stmt1 . 
stmt ::= return . 
stmts ::= sstmt . 
stmts ::= stmts . sstmt
stmts ::= stmts sstmt . 
store ::= STORE_FAST . 
store ::= expr . STORE_ATTR
store_subscript ::= expr . expr STORE_SUBSCR
store_subscript ::= expr expr . STORE_SUBSCR
subscript ::= expr . expr BINARY_SUBSCR
subscript ::= expr expr . BINARY_SUBSCR
subscript ::= expr expr BINARY_SUBSCR . 
subscript2 ::= expr . expr DUP_TOP_TWO BINARY_SUBSCR
subscript2 ::= expr expr . DUP_TOP_TWO BINARY_SUBSCR
suite_stmts ::= _stmts . 
suite_stmts_opt ::= suite_stmts . 
testexpr ::= testfalse . 
testexpr_cf ::= testexpr . come_froms
testfalse ::= expr . jmp_false
testfalse ::= expr jmp_false . 
testfalse_not_and ::= expr . jmp_false expr jmp_true COME_FROM
testfalse_not_and ::= expr jmp_false . expr jmp_true COME_FROM
testfalse_not_and ::= expr jmp_false expr . jmp_true COME_FROM
testfalse_not_or ::= expr . jmp_false expr jmp_false COME_FROM
testfalse_not_or ::= expr jmp_false . expr jmp_false COME_FROM
testfalse_not_or ::= expr jmp_false expr . jmp_false COME_FROM
testfalsel ::= expr . jmp_true
testtrue ::= expr . jmp_true
try_elsestmtl38 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK except_handler38 COME_FROM else_suitel \e_opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK except_handler38 COME_FROM else_suitel opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK except_handler38 COME_FROM else_suitel \e_opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK except_handler38 COME_FROM else_suitel opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK except_handler38 COME_FROM else_suitel \e_opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK except_handler38 COME_FROM else_suitel opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . except_handler38 COME_FROM else_suitel \e_opt_come_from_except
try_elsestmtl38 ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . except_handler38 COME_FROM else_suitel opt_come_from_except
try_except ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK except_handler38
try_except ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK except_handler38
try_except ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK except_handler38
try_except ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . except_handler38
try_except38 ::= SETUP_FINALLY . POP_BLOCK POP_TOP \e_suite_stmts_opt except_handler38a
try_except38 ::= SETUP_FINALLY . POP_BLOCK POP_TOP suite_stmts_opt except_handler38a
try_except38 ::= SETUP_FINALLY . POP_BLOCK suite_stmts except_handler38b
try_except38r ::= SETUP_FINALLY . return_except except_handler38b
try_except38r ::= SETUP_FINALLY return_except . except_handler38b
try_except38r2 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP \e_cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP \e_cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP \e_cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP \e_cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r2 ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . JUMP_FORWARD COME_FROM_FINALLY POP_TOP POP_TOP POP_TOP cond_except_stmts_opt POP_EXCEPT return END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY \e_cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY \e_cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY \e_cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK JUMP_FORWARD COME_FROM_FINALLY cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . JUMP_FORWARD COME_FROM_FINALLY \e_cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r3 ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . JUMP_FORWARD COME_FROM_FINALLY cond_except_stmts_opt POP_EXCEPT return COME_FROM END_FINALLY COME_FROM
try_except38r4 ::= SETUP_FINALLY . returns_in_except COME_FROM_FINALLY except_cond1 return COME_FROM END_FINALLY
try_except38r4 ::= SETUP_FINALLY returns_in_except . COME_FROM_FINALLY except_cond1 return COME_FROM END_FINALLY
try_except38r4 ::= SETUP_FINALLY returns_in_except COME_FROM_FINALLY . except_cond1 return COME_FROM END_FINALLY
try_except_as ::= SETUP_FINALLY . POP_BLOCK suite_stmts except_handler_as END_FINALLY COME_FROM
try_except_as ::= SETUP_FINALLY . suite_stmts except_handler_as END_FINALLY COME_FROM
try_except_as ::= SETUP_FINALLY suite_stmts . except_handler_as END_FINALLY COME_FROM
try_except_ret38 ::= SETUP_FINALLY . returns except_ret38a
tryfinally36 ::= SETUP_FINALLY . returns COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinally36 ::= SETUP_FINALLY . returns COME_FROM_FINALLY suite_stmts
tryfinally36 ::= SETUP_FINALLY . returns COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinally38astmt ::= LOAD_CONST . SETUP_FINALLY \e_suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY POP_TOP \e_suite_stmts_opt END_FINALLY POP_TOP
tryfinally38astmt ::= LOAD_CONST . SETUP_FINALLY \e_suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY POP_TOP suite_stmts_opt END_FINALLY POP_TOP
tryfinally38astmt ::= LOAD_CONST . SETUP_FINALLY suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY POP_TOP \e_suite_stmts_opt END_FINALLY POP_TOP
tryfinally38astmt ::= LOAD_CONST . SETUP_FINALLY suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY POP_TOP suite_stmts_opt END_FINALLY POP_TOP
tryfinally38rstmt3 ::= SETUP_FINALLY . expr POP_BLOCK CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY ss_end_finally
tryfinally38rstmt3 ::= SETUP_FINALLY expr . POP_BLOCK CALL_FINALLY RETURN_VALUE COME_FROM COME_FROM_FINALLY ss_end_finally
tryfinally38stmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinally38stmt ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . BEGIN_FINALLY COME_FROM_FINALLY POP_FINALLY suite_stmts_opt END_FINALLY
tryfinally_return_stmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK LOAD_CONST COME_FROM_FINALLY
tryfinally_return_stmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY
tryfinally_return_stmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY
tryfinally_return_stmt ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . LOAD_CONST COME_FROM_FINALLY
tryfinally_return_stmt ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK LOAD_CONST . COME_FROM_FINALLY
tryfinallystmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK LOAD_CONST COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY . suite_stmts_opt POP_BLOCK LOAD_CONST COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY \e_suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK BEGIN_FINALLY COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt . POP_BLOCK LOAD_CONST COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . BEGIN_FINALLY COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . BEGIN_FINALLY COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . LOAD_CONST COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK . LOAD_CONST COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK LOAD_CONST . COME_FROM_FINALLY \e_suite_stmts_opt END_FINALLY
tryfinallystmt ::= SETUP_FINALLY suite_stmts_opt POP_BLOCK LOAD_CONST . COME_FROM_FINALLY suite_stmts_opt END_FINALLY
tuple ::= expr . expr BUILD_TUPLE_2
tuple ::= expr expr . BUILD_TUPLE_2
unary_not ::= expr . UNARY_NOT
unary_op ::= expr . unary_operator
while1stmt ::= \e__come_froms . l_stmts COME_FROM JUMP_BACK COME_FROM_LOOP
while1stmt ::= \e__come_froms l_stmts . COME_FROM JUMP_BACK COME_FROM_LOOP
while1stmt ::= \e__come_froms l_stmts COME_FROM . JUMP_BACK COME_FROM_LOOP
while1stmt ::= _come_froms . l_stmts COME_FROM JUMP_BACK COME_FROM_LOOP
while1stmt ::= _come_froms l_stmts . COME_FROM JUMP_BACK COME_FROM_LOOP
while1stmt ::= _come_froms l_stmts COME_FROM . JUMP_BACK COME_FROM_LOOP
whileTruestmt ::= \e__come_froms . l_stmts JUMP_BACK POP_BLOCK
whileTruestmt ::= \e__come_froms l_stmts . JUMP_BACK POP_BLOCK
whileTruestmt ::= _come_froms . l_stmts JUMP_BACK POP_BLOCK
whileTruestmt ::= _come_froms l_stmts . JUMP_BACK POP_BLOCK
whileTruestmt38 ::= \e__come_froms . l_stmts JUMP_BACK
whileTruestmt38 ::= \e__come_froms . l_stmts JUMP_BACK COME_FROM_EXCEPT_CLAUSE
whileTruestmt38 ::= \e__come_froms . pass JUMP_BACK
whileTruestmt38 ::= \e__come_froms \e_pass . JUMP_BACK
whileTruestmt38 ::= \e__come_froms l_stmts . JUMP_BACK
whileTruestmt38 ::= \e__come_froms l_stmts . JUMP_BACK COME_FROM_EXCEPT_CLAUSE
whileTruestmt38 ::= _come_froms . l_stmts JUMP_BACK
whileTruestmt38 ::= _come_froms . l_stmts JUMP_BACK COME_FROM_EXCEPT_CLAUSE
whileTruestmt38 ::= _come_froms . pass JUMP_BACK
whileTruestmt38 ::= _come_froms \e_pass . JUMP_BACK
whileTruestmt38 ::= _come_froms l_stmts . JUMP_BACK
whileTruestmt38 ::= _come_froms l_stmts . JUMP_BACK COME_FROM_EXCEPT_CLAUSE
whilestmt38 ::= \e__come_froms . testexpr \e_l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms . testexpr \e_l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms . testexpr \e_l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= \e__come_froms . testexpr l_stmts JUMP_BACK
whilestmt38 ::= \e__come_froms . testexpr l_stmts come_froms
whilestmt38 ::= \e__come_froms . testexpr l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms . testexpr l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms . testexpr l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= \e__come_froms . testexpr returns POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr . l_stmts JUMP_BACK
whilestmt38 ::= \e__come_froms testexpr . l_stmts come_froms
whilestmt38 ::= \e__come_froms testexpr . l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr . l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr . l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= \e__come_froms testexpr . returns POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr \e_l_stmts_opt . COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr \e_l_stmts_opt . JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr \e_l_stmts_opt . JUMP_BACK come_froms
whilestmt38 ::= \e__come_froms testexpr l_stmts . JUMP_BACK
whilestmt38 ::= \e__come_froms testexpr l_stmts . come_froms
whilestmt38 ::= \e__come_froms testexpr l_stmts come_froms . 
whilestmt38 ::= \e__come_froms testexpr l_stmts_opt . COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr l_stmts_opt . JUMP_BACK POP_BLOCK
whilestmt38 ::= \e__come_froms testexpr l_stmts_opt . JUMP_BACK come_froms
whilestmt38 ::= \e__come_froms testexpr l_stmts_opt COME_FROM . JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms . testexpr \e_l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms . testexpr \e_l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms . testexpr \e_l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= _come_froms . testexpr l_stmts JUMP_BACK
whilestmt38 ::= _come_froms . testexpr l_stmts come_froms
whilestmt38 ::= _come_froms . testexpr l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms . testexpr l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms . testexpr l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= _come_froms . testexpr returns POP_BLOCK
whilestmt38 ::= _come_froms testexpr . l_stmts JUMP_BACK
whilestmt38 ::= _come_froms testexpr . l_stmts come_froms
whilestmt38 ::= _come_froms testexpr . l_stmts_opt COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr . l_stmts_opt JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr . l_stmts_opt JUMP_BACK come_froms
whilestmt38 ::= _come_froms testexpr . returns POP_BLOCK
whilestmt38 ::= _come_froms testexpr \e_l_stmts_opt . COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr \e_l_stmts_opt . JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr \e_l_stmts_opt . JUMP_BACK come_froms
whilestmt38 ::= _come_froms testexpr l_stmts . JUMP_BACK
whilestmt38 ::= _come_froms testexpr l_stmts . come_froms
whilestmt38 ::= _come_froms testexpr l_stmts come_froms . 
whilestmt38 ::= _come_froms testexpr l_stmts_opt . COME_FROM JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr l_stmts_opt . JUMP_BACK POP_BLOCK
whilestmt38 ::= _come_froms testexpr l_stmts_opt . JUMP_BACK come_froms
whilestmt38 ::= _come_froms testexpr l_stmts_opt COME_FROM . JUMP_BACK POP_BLOCK
yield ::= expr . YIELD_VALUE
yield_from ::= expr . GET_YIELD_FROM_ITER LOAD_CONST YIELD_FROM
Instruction context:
   
 L. 213        18  DUP_TOP          
                  20  LOAD_GLOBAL              TwentyError
                  22  COMPARE_OP               exception-match
                  24  POP_JUMP_IF_FALSE    68  'to 68'
                  26  POP_TOP          
->                28  STORE_FAST               'e'
                  30  POP_TOP          
                  32  SETUP_FINALLY        56  'to 56'

from __future__ import annotations
import logging, os, re, time
from typing import Any, Iterable
import httpx
logger = logging.getLogger(__name__)

def upper_enum(value: "str | None") -> "str | None":
    """
    Normalise a string to UPPER_SNAKE_CASE for Twenty SELECT / MULTI_SELECT
    values. Twenty rejects anything else with `INVALID_FIELD_INPUT`.

    Examples:
      'web'          -> 'WEB'
      'mobile_ios'   -> 'MOBILE_IOS'
      'individual'   -> 'INDIVIDUAL'
      'MarketIntel'  -> 'MARKET_INTEL'
      'Strong Sell'  -> 'STRONG_SELL'
    """
    if value is None:
        return
    s = str(value)
    s = re.sub("([a-z0-9])([A-Z])", "\\1_\\2", s)
    s = re.sub("[^A-Za-z0-9]+", "_", s)
    return s.upper().strip("_")


class TwentyError(RuntimeError):
    __doc__ = "Raised when a GraphQL response contains errors we cannot recover from."


class TwentyAuthError(TwentyError):
    __doc__ = "Raised on 401/403 — API key invalid or missing permissions."


class TwentyBadInputError(TwentyError):
    __doc__ = "Raised on GraphQL BAD_USER_INPUT / VALIDATION_FAILED / METADATA_VALIDATION_FAILED\n    — these are permanent per-row failures and are NEVER retried."


class TwentyClient:
    __doc__ = "\n    Thin GraphQL client for Twenty CRM.\n\n    Prefer TwentyClient.from_env() unless you need explicit config (tests, etc.).\n    "

    def __init__(self, base_url, api_key, *, timeout=30.0, max_retries=3, retry_backoff_sec=1.0):
        if not api_key:
            raise TwentyAuthError("api_key is empty")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_sec = retry_backoff_sec
        self._client = httpx.Client(timeout=timeout,
          headers={'Authorization':f"Bearer {api_key}", 
         'Content-Type':"application/json"})

    @classmethod
    def from_env(cls) -> "'TwentyClient'":
        base = os.environ.get("TWENTY_STOCK_URL", "https://crm-stock.datap.ai")
        key = os.environ.get("TWENTY_STOCK_API_KEY", "")
        return cls(base, key)

    def close(self) -> "None":
        self._client.close()

    def __enter__(self) -> "'TwentyClient'":
        return self

    def __exit__(self, *exc) -> "None":
        self.close()

    def _postParse error at or near `ROT_TWO' instruction at offset 260

    def graphql(self, query: "str", variables: "dict | None"=None) -> "dict":
        """POST to /graphql (workspace-scoped record queries)."""
        return self._post("/graphql", query, variables)

    def metadata(self, query: "str", variables: "dict | None"=None) -> "dict":
        """POST to /metadata (object/field/role queries + mutations)."""
        return self._post("/metadata", query, variables)

    def pingParse error at or near `STORE_FAST' instruction at offset 28

    def find_one(self, object_name_plural, *, filter=None, fields=('id', )):
        """
        Return a single record matching `filter`, or None.

        `object_name_plural` is the GraphQL query field name — e.g. "stockClients"
        for the stockClient object, "people" for the built-in Person object.

        `filter` uses Twenty's filter shape, e.g. {"email": {"eq": "donny@datap.ai"}}.

        `fields` is the GraphQL selection set for `node { ... }`.
        """
        fields_selection = " ".join(fields)
        query = f"\n        query FindOne($filter: {_filter_type(object_name_plural)}) {{\n          {object_name_plural}(filter: $filter, first: 1) {{\n            edges {{ node {{ {fields_selection} }} }}\n          }}\n        }}\n        "
        data = self.graphql(query, {"filter": (filter or {})})
        edges = data.get(object_name_plural, {}).get("edges", [])
        if edges:
            return edges[0]["node"]

    def find_many(self, object_name_plural, *, filter=None, fields=('id', ), first=100):
        """Return up to `first` records matching `filter`. Does NOT paginate."""
        fields_selection = " ".join(fields)
        query = f"\n        query FindMany($filter: {_filter_type(object_name_plural)}, $first: Int) {{\n          {object_name_plural}(filter: $filter, first: $first) {{\n            edges {{ node {{ {fields_selection} }} }}\n            totalCount\n          }}\n        }}\n        "
        data = self.graphql(query, {'filter':filter or {},  'first':first})
        return [e["node"] for e in data.get(object_name_plural, {}).get("edges", [])]

    def create_record(self, object_name_singular, data, *, return_fields=('id', )):
        """Create a single record. Returns the fields in `return_fields`."""
        mutation_name = f"create{_capitalize_first(object_name_singular)}"
        input_type = f"{_capitalize_first(object_name_singular)}CreateInput!"
        fields_selection = " ".join(return_fields)
        query = f"\n        mutation Create($data: {input_type}) {{\n          {mutation_name}(data: $data) {{ {fields_selection} }}\n        }}\n        "
        result = self.graphql(query, {"data": data})
        return result[mutation_name]

    def update_record(self, object_name_singular, record_id, data, *, return_fields=('id', )):
        """Update a single record by id."""
        mutation_name = f"update{_capitalize_first(object_name_singular)}"
        input_type = f"{_capitalize_first(object_name_singular)}UpdateInput!"
        fields_selection = " ".join(return_fields)
        query = f"\n        mutation Update($id: UUID!, $data: {input_type}) {{\n          {mutation_name}(id: $id, data: $data) {{ {fields_selection} }}\n        }}\n        "
        result = self.graphql(query, {'id':record_id,  'data':data})
        return result[mutation_name]

    def delete_record(self, object_name_singular: "str", record_id: "str") -> "dict":
        """Soft-delete a single record by id."""
        mutation_name = f"delete{_capitalize_first(object_name_singular)}"
        query = f"\n        mutation Delete($id: UUID!) {{\n          {mutation_name}(id: $id) {{ id }}\n        }}\n        "
        result = self.graphql(query, {"id": record_id})
        return result[mutation_name]

    def upsert_by_field(self, object_name_singular, object_name_plural, dedup_field, row, *, known_fields=('id', )):
        """
        Find-or-create a record by a unique field (e.g. email).

        Returns a tuple:
          ("created", {...record}) if the record was created
          ("updated", {...record}) if it existed and was updated
        """
        dedup_value = row.get(dedup_field)
        if dedup_value is None:
            raise ValueError(f"row missing dedup field {dedup_field}: {row}")
        existing = self.find_one(object_name_plural,
          filter={dedup_field: {"eq": dedup_value}},
          fields=known_fields)
        if existing:
            update_payload = {k: v for k, v in row.items() if k != dedup_field}
            if not update_payload:
                return (
                 "updated", existing)
            result = self.update_record(object_name_singular,
              (existing["id"]), update_payload, return_fields=known_fields)
            return (
             "updated", result)
        result = self.create_record(object_name_singular, row, return_fields=known_fields)
        return ("created", result)

    def bulk_upsert(self, object_name_singular, object_name_plural, rows, dedup_field, *, known_fields=('id', )):
        """
        Upsert many rows by a unique field. Logs per-row failures and
        continues — does NOT abort on a single bad row.

        Returns: {"created": N, "updated": M, "failed": K}
        """
        created = updated = failed = 0
        for row in rows:
            try:
                kind, _ = self.upsert_by_field(object_name_singular,
                  object_name_plural,
                  dedup_field,
                  row,
                  known_fields=known_fields)
                if kind == "created":
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                try:
                    failed += 1
                    logger.error("upsert failed for %s %s=%s: %s", object_name_singular, dedup_field, row.get(dedup_field), e)
                finally:
                    e = None
                    del e

        else:
            return {'created':created, 
             'updated':updated,  'failed':failed}


def _capitalize_first(s: "str") -> "str":
    """stockClient -> StockClient."""
    return s[None[:1]].upper() + s[1[:None]]


def _filter_type(object_name_plural: "str") -> "str":
    """
    Twenty's auto-generated filter input type name follows the pattern
    `{PascalCaseSingular}FilterInput`. For plural 'stockClients' the type is
    'StockClientFilterInput'. This helper assumes a simple -s plural.
    """
    singular = object_name_plural[None[:-1]] if object_name_plural.endswith("s") else object_name_plural
    return f"{_capitalize_first(singular)}FilterInput"
