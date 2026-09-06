import http from 'k6/http';
import { loadDataset } from '../lib/data.js';

const dataset = loadDataset();
export const options = {vus: 1, iterations: 1};
export default function () {
    const url = `http://backend:8080/sessions/${dataset.seatMapSessionId}/seats`;
    for (const mode of ['default', 'gzip']) {
        const params = mode === 'gzip' ? {headers: {'Accept-Encoding': 'gzip'}} : {};
        const response = http.get(url, {...params, tags: {name: 'seat map encoding probe'}});
        console.log(JSON.stringify({
            mode, status: response.status,
            requestAcceptEncoding: response.request.headers['Accept-Encoding'] || null,
            contentEncoding: response.headers['Content-Encoding'] || null,
            contentLength: response.headers['Content-Length'] || null,
            transferEncoding: response.headers['Transfer-Encoding'] || null,
            decodedBodyLength: response.body.length,
        }));
        if (response.status !== 200) throw new Error('Seat Map encoding probe failed');
    }
}
