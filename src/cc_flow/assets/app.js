// Configure marked
marked.setOptions({
    breaks: true,
    gfm: true,
    highlight: function(code, lang) {
        if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
        }
        return hljs.highlightAuto(code).value;
    }
});

const segments = data.segments;
const subagents = data.subagents;

let currentView = 'root';
let navigationStack = ['root'];

const CARD_WIDTH = 440, CARD_GAP_Y = 45, BRANCH_GAP_X = 500;
const SEGMENT_GAP = 560;
const PADDING = 60, HEADER_HEIGHT = 50;

let scale = 1, translateX = PADDING, translateY = PADDING;
let isDragging = false, dragStartX, dragStartY;

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

function formatTokens(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(0) + 'K';
    return n.toString();
}

const COPY_ICON = '<svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>';
const CHECK_ICON = '<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>';

function copyTurnContent(turnKey, btn) {
    const turn = turnDataMap[turnKey];
    if (!turn) return;

    let text = `Human: ${turn.user_message}\n\n`;
    turn.blocks.forEach(block => {
        if (block.type === 'text') {
            text += `${block.content}\n\n`;
        } else if (block.type === 'tool_use') {
            text += `[Tool: ${block.tool_name}] ${block.tool_input}\n\n`;
        }
    });

    navigator.clipboard.writeText(text).then(() => {
        btn.classList.add('copied');
        btn.innerHTML = CHECK_ICON;
        setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = COPY_ICON;
        }, 2000);
    });
}

function navigateTo(viewId) {
    if (viewId === 'root') {
        currentView = 'root';
        navigationStack = ['root'];
    } else if (subagents[viewId]) {
        const idx = navigationStack.indexOf(viewId);
        if (idx >= 0) {
            navigationStack = navigationStack.slice(0, idx + 1);
        } else {
            navigationStack.push(viewId);
        }
        currentView = viewId;
    }
    resetView();
    render();
    updateBreadcrumb();
}

function updateBreadcrumb() {
    const bc = document.getElementById('breadcrumb');
    bc.innerHTML = navigationStack.map((id, i) => {
        const isLast = i === navigationStack.length - 1;
        const label = id === 'root' ? 'Session' : `Agent ${id.substring(0,7)}`;
        const sep = i < navigationStack.length - 1 ? '<span class="breadcrumb-sep">></span>' : '';
        return `<span class="breadcrumb-item ${isLast ? 'current' : ''}" onclick="navigateTo('${id}')">${label}</span>${sep}`;
    }).join('');
}

function renderMarkdown(text) {
    try {
        return marked.parse(text);
    } catch (e) {
        return escapeHtml(text);
    }
}

function createTurnCard(turn, localIndex, segmentId, segmentType) {
    const card = document.createElement('div');
    card.className = 'turn-card' + (turn.is_system ? ' system-message' : '');
    card.dataset.turnId = `${segmentId}:${turn.id}`;
    card.dataset.segmentType = segmentType;
    const timestamp = turn.user_timestamp ? turn.user_timestamp.substring(11, 19) : '';
    const messageLabel = turn.is_system ? 'System' : 'Human';

    let itemsHtml = '';
    turn.blocks.forEach(item => {
        // Skip tool_result in card preview - shown in modal
        if (item.type === 'tool_result') return;

        if (item.type === 'thinking') {
            // Compact: just header
            itemsHtml += `<div class="response-item compact"><div class="item-header">Thinking</div></div>`;
        } else if (item.type === 'text') {
            // Text: show content
            itemsHtml += `
                <div class="response-item item-text">
                    <div class="item-header">Text</div>
                    <div class="item-content markdown">${renderMarkdown(item.content)}</div>
                </div>`;
        } else if (item.type === 'tool_use') {
            // Compact: just tool name
            const toolName = item.tool_name + (item.subagent_type ? ` (${item.subagent_type})` : '');
            let drillBtn = '';
            if (item.child_agent_id && subagents[item.child_agent_id]) {
                drillBtn = `<button class="drill-btn" onclick="event.stopPropagation();navigateTo('${item.child_agent_id}')" style="margin-left:auto;padding:4px 8px;font-size:0.65rem;">Enter</button>`;
            }
            itemsHtml += `<div class="response-item compact"><div class="item-header">${toolName}</div>${drillBtn}</div>`;
        }
    });

    const turnKey = `${segmentId}:${turn.id}`;

    // Build image attachments HTML
    let imagesHtml = '';
    if (turn.images && turn.images.length > 0) {
        const imageLinks = turn.images.map((img, i) => {
            const hasEmbed = !!img.data_url;
            return `<a class="image-link ${hasEmbed ? 'has-preview' : ''}"
                href="javascript:void(0)"
                data-turn-key="${turnKey}"
                data-image-index="${i}"
                title="${hasEmbed ? 'Click to view image' : 'Image not embedded'}">
                <svg viewBox="0 0 24 24"><path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/></svg>
                <span>[Image ${i + 1}] ${escapeHtml(img.path)}</span>
            </a>`;
        }).join('');
        imagesHtml = `<div class="image-attachments">${imageLinks}</div>`;
    }

    card.innerHTML = `
        <div class="turn-header">
            <span class="turn-time">${timestamp}</span>
            <button class="copy-btn" onclick="event.stopPropagation();copyTurnContent('${turnKey}', this)">${COPY_ICON}</button>
        </div>
        <div class="user-message">
            <div class="user-label">${messageLabel}</div>
            ${escapeHtml(turn.user_message)}
        </div>
        ${imagesHtml}
        ${itemsHtml ? `<div class="response-items">${itemsHtml}</div>` : ''}
    `;
    return card;
}

function createSegmentHeader(segment) {
    const header = document.createElement('div');
    header.className = `segment-header ${segment.type}`;

    let label, meta = '';
    if (segment.type === 'continuation') {
        label = 'Continued';
        const tokens = segment.compact_metadata?.pre_tokens || 0;
        if (tokens) meta = `${formatTokens(tokens)} tokens compacted`;
    } else {
        label = 'Original';
        meta = `${segment.turns.length} turns`;
    }

    header.innerHTML = `
        <span class="segment-label">${label}</span>
        <span class="segment-meta">${meta}</span>
    `;
    return header;
}

function render() {
    const canvas = document.getElementById('canvas');
    canvas.querySelectorAll('.turn-card, .segment-header, .empty-message, .segment-divider').forEach(el => el.remove());

    let allPositions = {};
    let allHeights = {};
    let totalTurns = 0;
    turnDataMap = {}; // Clear turn data on re-render

    // Handle empty state
    if (currentView === 'root' && segments.length === 0) {
        const emptyMsg = document.createElement('div');
        emptyMsg.className = 'empty-message';
        emptyMsg.innerHTML = '<h2>No conversation found</h2><p>The session file contains no user messages.</p>';
        canvas.appendChild(emptyMsg);
        document.getElementById('segment-count').textContent = '0 segments';
        document.getElementById('turn-count').textContent = '0 turns';
        return;
    }

    if (currentView === 'root') {
        // Render segments side by side
        let segmentX = 0;

        segments.forEach((segment, segIdx) => {
            const turns = segment.turns;
            totalTurns += turns.length;

            // Create segment header
            const headerEl = createSegmentHeader(segment);
            headerEl.style.position = 'absolute';
            headerEl.style.left = segmentX + 'px';
            headerEl.style.top = '0px';
            canvas.appendChild(headerEl);

            // Measure card heights
            const heights = {};
            turns.forEach((turn, i) => {
                const card = createTurnCard(turn, i, segment.id, segment.type);
                canvas.appendChild(card);
                heights[turn.id] = card.offsetHeight;
                card.remove();
            });

            // Layout this segment
            const positions = {};
            const turnById = {};
            turns.forEach(t => turnById[t.id] = t);

            const roots = turns.filter(t => t.parent_turn_id === null);
            let localX = segmentX;

            function layoutSubtree(turnId, x, y) {
                const turn = turnById[turnId];
                if (!turn) return { width: 0, height: 0 };
                const posKey = `${segment.id}:${turnId}`;
                positions[posKey] = { x, y, segmentId: segment.id, turnId: turnId };
                const children = turns.filter(t => t.parent_turn_id === turnId);
                if (children.length === 0) return { width: CARD_WIDTH, height: heights[turnId] };
                let childY = y + heights[turnId] + CARD_GAP_Y;
                let totalWidth = 0;
                children.forEach((child, i) => {
                    const childX = x + totalWidth;
                    const subtree = layoutSubtree(child.id, childX, childY);
                    totalWidth += subtree.width + (i < children.length - 1 ? BRANCH_GAP_X - CARD_WIDTH : 0);
                });
                return { width: Math.max(CARD_WIDTH, totalWidth), height: heights[turnId] };
            }

            let maxWidth = 0;
            roots.forEach(root => {
                layoutSubtree(root.id, localX, HEADER_HEIGHT);
                const maxX = Math.max(...Object.values(positions).filter(p => p.segmentId === segment.id).map(p => p.x));
                localX = maxX + CARD_WIDTH + BRANCH_GAP_X;
                maxWidth = Math.max(maxWidth, maxX + CARD_WIDTH - segmentX);
            });

            // Render cards for this segment
            turns.forEach((turn, i) => {
                const card = createTurnCard(turn, i, segment.id, segment.type);
                const posKey = `${segment.id}:${turn.id}`;
                const pos = positions[posKey];
                if (pos) {
                    card.style.left = pos.x + 'px';
                    card.style.top = pos.y + 'px';
                }
                storeTurnData(segment.id, turn);
                canvas.appendChild(card);
            });

            Object.assign(allPositions, positions);
            Object.assign(allHeights, heights);

            // Add segment divider (except after last segment)
            if (segIdx < segments.length - 1) {
                const dividerX = segmentX + maxWidth + SEGMENT_GAP / 2;
                const divider = document.createElement('div');
                divider.className = 'segment-divider';
                divider.style.left = dividerX + 'px';
                canvas.appendChild(divider);
            }

            segmentX += maxWidth + SEGMENT_GAP;
        });

        document.getElementById('segment-count').textContent = `${segments.length} segments`;
        document.getElementById('turn-count').textContent = `${totalTurns} turns`;

    } else {
        // Render subagent
        const turns = subagents[currentView] || [];
        totalTurns = turns.length;
        const subagentSegmentId = 'subagent';

        const heights = {};
        turns.forEach((turn, i) => {
            const card = createTurnCard(turn, i, subagentSegmentId, 'subagent');
            canvas.appendChild(card);
            heights[turn.id] = card.offsetHeight;
            card.remove();
        });

        const positions = {};
        const turnById = {};
        turns.forEach(t => turnById[t.id] = t);
        const roots = turns.filter(t => t.parent_turn_id === null);

        let globalX = 0;
        function layoutSubtree(turnId, x, y) {
            const turn = turnById[turnId];
            if (!turn) return { width: 0, height: 0 };
            const posKey = `${subagentSegmentId}:${turnId}`;
            positions[posKey] = { x, y, segmentId: subagentSegmentId, turnId: turnId };
            const children = turns.filter(t => t.parent_turn_id === turnId);
            if (children.length === 0) return { width: CARD_WIDTH, height: heights[turnId] };
            let childY = y + heights[turnId] + CARD_GAP_Y;
            let totalWidth = 0;
            children.forEach((child, i) => {
                const childX = x + totalWidth;
                const subtree = layoutSubtree(child.id, childX, childY);
                totalWidth += subtree.width + (i < children.length - 1 ? BRANCH_GAP_X - CARD_WIDTH : 0);
            });
            return { width: Math.max(CARD_WIDTH, totalWidth), height: heights[turnId] };
        }

        roots.forEach(root => {
            layoutSubtree(root.id, globalX, 0);
            const maxX = Math.max(...Object.values(positions).map(p => p.x), 0);
            globalX = maxX + CARD_WIDTH + BRANCH_GAP_X;
        });

        turns.forEach((turn, i) => {
            const card = createTurnCard(turn, i, subagentSegmentId, 'subagent');
            const posKey = `${subagentSegmentId}:${turn.id}`;
            const pos = positions[posKey];
            if (pos) { card.style.left = pos.x + 'px'; card.style.top = pos.y + 'px'; }
            storeTurnData(subagentSegmentId, turn);
            canvas.appendChild(card);
        });

        Object.assign(allPositions, positions);
        Object.assign(allHeights, heights);

        document.getElementById('segment-count').textContent = `subagent`;
        document.getElementById('turn-count').textContent = `${totalTurns} turns`;
    }

    // Draw edges
    const svg = document.querySelector('svg.edges');
    svg.innerHTML = '';
    let maxX = 0, maxY = 0;
    Object.values(allPositions).forEach(p => {
        maxX = Math.max(maxX, p.x + CARD_WIDTH);
        maxY = Math.max(maxY, p.y + 500);
    });
    svg.setAttribute('width', Math.max(maxX + PADDING, 100));
    svg.setAttribute('height', Math.max(maxY + PADDING, 100));

    // Flatten turns with segment context for composite key lookups
    const allTurns = currentView === 'root'
        ? segments.flatMap(s => s.turns.map(t => ({ ...t, _segmentId: s.id })))
        : (subagents[currentView] || []).map(t => ({ ...t, _segmentId: 'subagent' }));

    allTurns.forEach(turn => {
        if (turn.parent_turn_id === null) return;
        const parentPosKey = `${turn._segmentId}:${turn.parent_turn_id}`;
        const childPosKey = `${turn._segmentId}:${turn.id}`;
        const parentPos = allPositions[parentPosKey], childPos = allPositions[childPosKey];
        if (!parentPos || !childPos) return;
        const parentCard = document.querySelector(`[data-turn-id="${parentPosKey}"]`);
        const parentHeight = parentCard ? parentCard.offsetHeight : 200;
        const x1 = parentPos.x + CARD_WIDTH / 2, y1 = parentPos.y + parentHeight;
        const x2 = childPos.x + CARD_WIDTH / 2, y2 = childPos.y;
        const midY = (y1 + y2) / 2;
        const pathD = `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('class', 'edge');
        path.setAttribute('d', pathD);
        svg.appendChild(path);
    });

    // Detect and apply truncation to user messages
    document.querySelectorAll('.turn-card .user-message').forEach(el => {
        if (el.scrollHeight > 150) {
            el.classList.add('truncated');
        }
    });

    updateTransform();
}

function updateTransform() {
    document.getElementById('canvas').style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
    document.getElementById('zoom-level').textContent = `${Math.round(scale * 100)}%`;
}

function resetView() { scale = 1; translateX = PADDING; translateY = PADDING; updateTransform(); }
function zoomIn() { scale = Math.min(scale * 1.2, 3); updateTransform(); }
function zoomOut() { scale = Math.max(scale / 1.2, 0.2); updateTransform(); }

// Modal functions
let currentModalTurn = null;

// Group tool_use blocks with their corresponding tool_result
function groupBlocks(blocks) {
    const groups = [];
    const resultMap = new Map();

    // Index tool_results by tool_use_id
    blocks.filter(b => b.type === 'tool_result' && b.tool_use_id)
          .forEach(b => resultMap.set(b.tool_use_id, b));

    const usedResults = new Set();

    blocks.forEach(block => {
        if (block.type === 'tool_use') {
            const result = resultMap.get(block.tool_use_id);
            groups.push({
                groupType: 'tool',
                toolUse: block,
                toolResult: result || null
            });
            if (result) usedResults.add(block.tool_use_id);
        } else if (block.type === 'tool_result') {
            // Skip if already paired
            if (!usedResults.has(block.tool_use_id)) {
                groups.push({ groupType: 'standalone', block });
            }
        } else {
            groups.push({ groupType: 'standalone', block });
        }
    });

    return groups;
}

function openModal(turn) {
    currentModalTurn = turn;

    // Populate modal content
    const timestamp = turn.user_timestamp ? turn.user_timestamp.substring(11, 19) : '';
    document.getElementById('modal-time').textContent = timestamp;

    const userSection = document.getElementById('modal-user-section');
    const userLabel = document.getElementById('modal-user-label');
    const userMessage = document.getElementById('modal-user-message');

    userLabel.textContent = turn.is_system ? 'System' : 'Human';

    // Build user message with images
    let userContent = escapeHtml(turn.user_message);
    if (turn.images && turn.images.length > 0) {
        const imageLinks = turn.images.map((img, i) => {
            const hasEmbed = !!img.data_url;
            return `<a class="image-link ${hasEmbed ? 'has-preview' : ''}"
                onclick="openLightbox(${JSON.stringify(img).replace(/"/g, '&quot;')})"
                title="${hasEmbed ? 'Click to view image' : 'Image not embedded'}">
                <svg viewBox="0 0 24 24"><path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/></svg>
                <span>[Image ${i + 1}] ${escapeHtml(img.path)}</span>
            </a>`;
        }).join('');
        userContent += `<div class="image-attachments" style="margin-top: 12px; border: none; padding: 0;">${imageLinks}</div>`;
    }
    userMessage.innerHTML = userContent;

    if (turn.is_system) {
        userSection.classList.add('system-msg');
    } else {
        userSection.classList.remove('system-msg');
    }

    // Build response blocks using grouping
    const responseEl = document.getElementById('modal-response');
    let blocksHtml = '';

    if (turn.blocks && turn.blocks.length > 0) {
        const groups = groupBlocks(turn.blocks);
        let thinkingCounter = 0;

        groups.forEach((group) => {
            if (group.groupType === 'tool') {
                // Render unified tool group
                const toolUse = group.toolUse;
                const toolResult = group.toolResult;
                const toolName = toolUse.tool_name + (toolUse.subagent_type ? ` (${toolUse.subagent_type})` : '');

                let inputContent = escapeHtml(toolUse.tool_input);
                let expandInputLink = '';
                if (toolUse.is_truncated && toolUse.full_content) {
                    expandInputLink = `<span class="expand-link" data-block-id="${toolUse.tool_use_id}" data-content-type="input">[Show all]</span>`;
                }

                let resultContent = '';
                let expandResultLink = '';
                if (toolResult) {
                    resultContent = escapeHtml(toolResult.content);
                    if (toolResult.is_truncated && toolResult.full_content) {
                        expandResultLink = `<span class="expand-link" data-block-id="${toolResult.tool_use_id}" data-content-type="result">[Show all]</span>`;
                    }
                }

                let drillBtn = '';
                if (toolUse.child_agent_id) {
                    if (subagents[toolUse.child_agent_id]) {
                        drillBtn = `<button class="drill-btn" onclick="closeModal();navigateTo('${toolUse.child_agent_id}')">Enter subagent</button>`;
                    } else {
                        drillBtn = `<div class="subagent-unavailable" style="margin: 12px 14px;">Subagent data unavailable</div>`;
                    }
                }

                blocksHtml += `
                    <div class="modal-tool-group">
                        <div class="modal-tool-header">${toolName}</div>
                        <div class="modal-tool-input" data-block-id="${toolUse.tool_use_id}" data-content-type="input">${inputContent}</div>
                        ${expandInputLink ? `<div class="expand-container">${expandInputLink}</div>` : ''}
                        ${toolResult ? `
                            <div class="modal-tool-result" data-block-id="${toolResult.tool_use_id}" data-content-type="result">${resultContent}</div>
                            ${expandResultLink ? `<div class="expand-container">${expandResultLink}</div>` : ''}
                        ` : ''}
                        ${drillBtn}
                    </div>
                `;
            } else {
                // Render standalone block
                const block = group.block;

                if (block.type === 'thinking') {
                    let content = escapeHtml(block.content);
                    let expandLink = '';
                    const thinkingId = `thinking-${thinkingCounter++}`;
                    if (block.is_truncated && block.full_content) {
                        expandLink = `<span class="expand-link" data-thinking-id="${thinkingId}">[Show all]</span>`;
                    }
                    blocksHtml += `
                        <div class="modal-block thinking" data-thinking-id="${thinkingId}" onclick="this.classList.toggle('expanded')">
                            <div class="modal-block-header">Thinking</div>
                            <div class="modal-block-content">${content}</div>
                            ${expandLink}
                        </div>
                    `;
                } else if (block.type === 'text') {
                    blocksHtml += `
                        <div class="modal-block text">
                            <div class="modal-block-header">Text</div>
                            <div class="modal-block-content markdown">${renderMarkdown(block.content)}</div>
                        </div>
                    `;
                } else if (block.type === 'tool_result') {
                    // Standalone tool_result (orphaned)
                    let content = escapeHtml(block.content);
                    let expandLink = '';
                    if (block.is_truncated && block.full_content) {
                        expandLink = `<span class="expand-link" data-block-id="${block.tool_use_id}" data-content-type="orphan-result">[Show all]</span>`;
                    }
                    blocksHtml += `
                        <div class="modal-tool-group">
                            <div class="modal-tool-header">Result</div>
                            <div class="modal-tool-result" data-block-id="${block.tool_use_id}" data-content-type="orphan-result">${content}</div>
                            ${expandLink ? `<div class="expand-container">${expandLink}</div>` : ''}
                        </div>
                    `;
                }
            }
        });
    }

    responseEl.innerHTML = blocksHtml;

    // Add expand link handlers (toggle between truncated and full)
    responseEl.querySelectorAll('.expand-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.stopPropagation();
            const blockId = link.dataset.blockId;
            const contentType = link.dataset.contentType;
            const thinkingId = link.dataset.thinkingId;
            const isExpanded = link.dataset.expanded === 'true';

            if (thinkingId) {
                // Handle thinking block content toggle
                const thinkingBlock = turn.blocks.find(b => b.type === 'thinking' && b.is_truncated);
                if (thinkingBlock) {
                    const thinkingEl = responseEl.querySelector(`[data-thinking-id="${thinkingId}"]`);
                    if (thinkingEl) {
                        const contentEl = thinkingEl.querySelector('.modal-block-content');
                        if (contentEl) {
                            if (isExpanded) {
                                contentEl.textContent = thinkingBlock.content;
                                link.textContent = '[Show all]';
                                link.dataset.expanded = 'false';
                            } else {
                                contentEl.textContent = thinkingBlock.full_content;
                                link.textContent = '[Show less]';
                                link.dataset.expanded = 'true';
                            }
                        }
                    }
                }
            } else if (blockId && contentType) {
                // Handle tool input/result toggle
                let block;
                if (contentType === 'input') {
                    block = turn.blocks.find(b => b.type === 'tool_use' && b.tool_use_id === blockId);
                } else {
                    block = turn.blocks.find(b => b.type === 'tool_result' && b.tool_use_id === blockId);
                }

                if (block) {
                    const contentEl = responseEl.querySelector(`[data-block-id="${blockId}"][data-content-type="${contentType}"]`);
                    if (contentEl) {
                        if (isExpanded) {
                            contentEl.textContent = contentType === 'input' ? block.tool_input : block.content;
                            link.textContent = '[Show all]';
                            link.dataset.expanded = 'false';
                        } else if (block.full_content) {
                            contentEl.textContent = block.full_content;
                            link.textContent = '[Show less]';
                            link.dataset.expanded = 'true';
                        }
                    }
                }
            }
        });
    });

    // Show modal
    document.getElementById('modal-backdrop').classList.add('visible');
    document.getElementById('card-modal').classList.add('visible');
}

function closeModal() {
    document.getElementById('modal-backdrop').classList.remove('visible');
    document.getElementById('card-modal').classList.remove('visible');
    currentModalTurn = null;
}

function copyModalContent() {
    if (!currentModalTurn) return;

    let text = `Human: ${currentModalTurn.user_message}\n\n`;
    currentModalTurn.blocks.forEach(block => {
        if (block.type === 'text') {
            text += `${block.content}\n\n`;
        } else if (block.type === 'tool_use') {
            text += `[Tool: ${block.tool_name}] ${block.tool_input}\n\n`;
        }
    });

    const btn = document.getElementById('modal-copy-btn');
    navigator.clipboard.writeText(text).then(() => {
        btn.classList.add('copied');
        btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg> Copied';
        setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg> Copy';
        }, 2000);
    });
}

// Modal event listeners
document.getElementById('modal-backdrop').addEventListener('click', closeModal);
document.getElementById('card-modal').addEventListener('click', (e) => {
    // Close if clicking the modal container (outside the content)
    if (e.target === e.currentTarget) closeModal();
});
document.getElementById('modal-close-btn').addEventListener('click', closeModal);
document.getElementById('modal-copy-btn').addEventListener('click', copyModalContent);
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});

// Store turn data for copy/lookup
let turnDataMap = {};

function storeTurnData(segmentId, turn) {
    const key = `${segmentId}:${turn.id}`;
    turnDataMap[key] = turn;
}

const container = document.getElementById('canvas-container');

container.addEventListener('mousedown', (e) => {
    if (e.target.closest('.turn-card, .segment-header')) return;
    isDragging = true;
    dragStartX = e.clientX - translateX;
    dragStartY = e.clientY - translateY;
});

container.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    translateX = e.clientX - dragStartX;
    translateY = e.clientY - dragStartY;
    updateTransform();
});

container.addEventListener('mouseup', () => isDragging = false);
container.addEventListener('mouseleave', () => isDragging = false);

// Card click handler - open modal
container.addEventListener('click', (e) => {
    const card = e.target.closest('.turn-card');
    if (!card) return;
    // Skip if clicking interactive elements
    if (e.target.closest('button, .drill-btn, .image-link')) return;

    const turnKey = card.dataset.turnId;
    const turn = turnDataMap[turnKey];
    if (turn) {
        openModal(turn);
    }
});

// Image link click handler (for card view)
container.addEventListener('click', (e) => {
    const imageLink = e.target.closest('.image-link');
    if (!imageLink) return;

    e.stopPropagation();
    e.preventDefault();

    const turnKey = imageLink.dataset.turnKey;
    const imageIndex = parseInt(imageLink.dataset.imageIndex, 10);
    const turn = turnDataMap[turnKey];

    if (turn && turn.images && turn.images[imageIndex]) {
        openLightbox(turn.images[imageIndex]);
    }
});

container.addEventListener('wheel', (e) => {
    if (e.target.closest('.response-items')) return;
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    const newScale = Math.max(0.2, Math.min(3, scale * delta));
    const rect = container.getBoundingClientRect();
    const mouseX = e.clientX - rect.left, mouseY = e.clientY - rect.top;
    translateX = mouseX - (mouseX - translateX) * (newScale / scale);
    translateY = mouseY - (mouseY - translateY) * (newScale / scale);
    scale = newScale;
    updateTransform();
});

// Image Lightbox functions
let currentLightboxPath = '';

function openLightbox(imgObj) {
    // imgObj has: { path: string, data_url?: string }
    const lightbox = document.getElementById('image-lightbox');
    const img = document.getElementById('lightbox-image');
    const pathEl = document.getElementById('lightbox-path');
    const errorEl = document.getElementById('lightbox-error');
    const copyBtn = document.getElementById('lightbox-copy-btn');

    currentLightboxPath = imgObj.path;

    // Reset state
    copyBtn.classList.remove('copied');
    copyBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg> Copy path to clipboard';

    // Set path display
    pathEl.textContent = imgObj.path;

    if (imgObj.data_url) {
        // Embedded image - show directly
        img.style.display = 'block';
        errorEl.classList.remove('visible');
        img.src = imgObj.data_url;
    } else {
        // No embedded data - show error message
        img.style.display = 'none';
        errorEl.classList.add('visible');
    }

    lightbox.classList.add('visible');
}

function closeLightbox() {
    document.getElementById('image-lightbox').classList.remove('visible');
    document.getElementById('lightbox-image').src = '';
    currentLightboxPath = '';
}

function copyLightboxPath() {
    if (!currentLightboxPath) return;
    const btn = document.getElementById('lightbox-copy-btn');
    navigator.clipboard.writeText(currentLightboxPath).then(() => {
        btn.classList.add('copied');
        btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg> Copied!';
        setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg> Copy path to clipboard';
        }, 2000);
    });
}

// Lightbox event listeners
document.getElementById('lightbox-close').addEventListener('click', closeLightbox);
document.getElementById('lightbox-copy-btn').addEventListener('click', copyLightboxPath);
document.getElementById('image-lightbox').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeLightbox();
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeLightbox();
    }
});

render();
