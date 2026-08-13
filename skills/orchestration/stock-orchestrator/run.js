'use strict';

require('dotenv').config({ path: require('path').resolve(__dirname, '../../../../.env') });
const fs = require('fs');
const path = require('path');
const { GoogleGenAI } = require('@google/genai');
let db;
try {
    db = require('../../../Modules/db_state_manager.js');
} catch (e) {
    console.warn("[WARNING] db_state_manager 無法載入 (可能是 DATABASE_URL 未設定):", e.message);
    db = {
        startLockHeartbeat: () => (() => {}),
        pool: { end: async () => {} }
    };
}

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
const MODEL_NAME = 'gemini-2.5-pro';

async function getPayload() {
    const args = process.argv.slice(2).join(' ');
    if (args.trim().length > 0) return args;
    return new Promise((resolve) => {
        let data = '';
        process.stdin.setEncoding('utf8');
        process.stdin.on('data', chunk => { data += chunk; });
        process.stdin.on('end', () => resolve(data));
        setTimeout(() => resolve(data), 1000);
    });
}

function purifyPayload(payload) {
    const cleanPayload = { ...payload };
    const SENSITIVE_KEYS = ['password', 'secret', 'token', 'apikey', 'api_key', 'authorization', 'private_key'];
    Object.keys(cleanPayload).forEach(key => {
        if (SENSITIVE_KEYS.some(sk => key.toLowerCase().includes(sk))) {
            delete cleanPayload[key];
        }
    });
    return cleanPayload;
}

async function invokeSubmodule(moduleName, inputData) {
    const skillPath = path.resolve(__dirname, '../', moduleName, 'SKILL.md');
    if (!fs.existsSync(skillPath)) {
        throw new Error(`Submodule ${moduleName} SKILL.md not found.`);
    }
    const systemPrompt = fs.readFileSync(skillPath, 'utf8');
    
    if (!process.env.GEMINI_API_KEY) {
        console.warn("[WARNING] GEMINI_API_KEY 未設定，回傳模擬 (Mock) LLM 結果。");
        if (inputData.objective) {
            // Mock submodule analysis
            return {
                analysis: `${moduleName} 分析完成`,
                key_insights: ["指標正常", "符合預期"]
            };
        }
    }

    const response = await ai.models.generateContent({
        model: MODEL_NAME,
        contents: `[使用者輸入資料]:\n${JSON.stringify(inputData, null, 2)}\n\n請根據上方資料與你的系統職責，產生分析結果。請僅回傳 JSON 格式的分析報告，不要包含 markdown code blocks 或其他贅述。`,
        config: {
            systemInstruction: systemPrompt,
            responseMimeType: "application/json"
        }
    });

    return JSON.parse(response.text());
}

async function mockRoutingLLM(purifiedPayload) {
    console.warn("[WARNING] GEMINI_API_KEY 未設定，回傳模擬 (Mock) 路由結果。");
    return ["financial-analyst", "pe-river-map"];
}

async function mockAggregateLLM(purifiedPayload, results) {
    console.warn("[WARNING] GEMINI_API_KEY 未設定，回傳模擬 (Mock) 彙整結果。");
    return {
        summary: "這是一份模擬的總管彙整報告。",
        details: results,
        conclusions: ["這是一項值得投資的標的 (Mock)"]
    };
}

async function main() {
    let stopHeartbeat = null;
    const agentId = 'stock-orchestrator-skill';
    let inputPayload = {};

    try {
        const rawOutput = await getPayload();
        if (!rawOutput || rawOutput.trim() === '') throw new Error("Empty input received.");

        // Clean null bytes and unprintable characters
        const sanitizedOutput = rawOutput.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '');

        try { 
            inputPayload = JSON.parse(sanitizedOutput); 
        } catch (e) { 
            // If it's not JSON, treat it as raw text input
            inputPayload = { objective: sanitizedOutput };
        }

        const purifiedPayload = purifyPayload(inputPayload);

        // Start Heartbeat Extension (防死鎖機制)
        stopHeartbeat = db.startLockHeartbeat('06_Stock_Analysis_Loop', agentId, 60);

        // 1. Intent Parsing
        const orchestratorPrompt = fs.readFileSync(path.resolve(__dirname, 'SKILL.md'), 'utf8');
        let targetModules = [];
        
        if (!process.env.GEMINI_API_KEY) {
            targetModules = await mockRoutingLLM(purifiedPayload);
        } else {
            const routingResponse = await ai.models.generateContent({
                model: MODEL_NAME,
                contents: `使用者的意圖/資料為：${JSON.stringify(purifiedPayload)}\n請決定需要依序調用哪些子模組（例如 financial-analyst, pe-river-map 等）。回傳格式必須是一個 JSON Array，包含要呼叫的模組名稱字串。`,
                config: {
                    systemInstruction: orchestratorPrompt,
                    responseMimeType: "application/json"
                }
            });

            targetModules = JSON.parse(routingResponse.text());
            if (!Array.isArray(targetModules)) {
                throw new Error("Routing LLM did not return an array of modules.");
            }
        }

        // 2. Promise Loop for dispatching
        const results = {};
        for (const moduleName of targetModules) {
            try {
                // To avoid sequential blocking entirely, they could be Promise.all, 
                // but for stock analysis, sequential is often safer to build context.
                // Doing sequential for now.
                const moduleResult = await invokeSubmodule(moduleName, purifiedPayload);
                results[moduleName] = moduleResult;
            } catch (err) {
                results[moduleName] = { error: err.message };
            }
        }

        // 3. Map-Reduce / Aggregate
        let finalOutput;
        if (!process.env.GEMINI_API_KEY) {
            finalOutput = await mockAggregateLLM(purifiedPayload, results);
        } else {
            const aggregateResponse = await ai.models.generateContent({
                model: MODEL_NAME,
                contents: `使用者的原始意圖：${JSON.stringify(purifiedPayload)}\n各子模組分析結果：${JSON.stringify(results, null, 2)}\n請將這些資料轉化為一份流暢、專業且易讀的「投資分析綜合報告」。請嚴格回傳純 JSON 數據，格式必須包含 { "summary": "...", "details": {...}, "conclusions": [...] }。`,
                config: {
                    systemInstruction: orchestratorPrompt,
                    responseMimeType: "application/json"
                }
            });
            finalOutput = JSON.parse(aggregateResponse.text());
        }

        // Output ONLY the JSON result to stdout for the next layer
        console.log(JSON.stringify(finalOutput, null, 2));

    } catch (error) {
        console.log(JSON.stringify({
            status: "FAILED",
            reason: error.message
        }, null, 2));
    } finally {
        if (stopHeartbeat) stopHeartbeat();
        try { await db.pool.end(); } catch (e) {}
    }
}

main();
