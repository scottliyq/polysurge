export default async function handler(req, res) {
    // Set CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
    res.setHeader('Cache-Control', 'no-store');

    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    const { market, limit = 500 } = req.query;

    try {
        let url = `https://data-api.polymarket.com/trades?limit=${limit}`;
        if (market) {
            url += `&market=${encodeURIComponent(market)}`;
        }

        const response = await fetch(url, {
            headers: {
                'User-Agent': 'PolySurge/1.0'
            }
        });

        if (!response.ok) {
            throw new Error(`API responded with ${response.status}`);
        }

        const data = await response.json();
        return res.status(200).json(data);
    } catch (error) {
        console.error('Trades API error:', error);
        return res.status(500).json({ error: error.message });
    }
}
