You are an expert technical editor. Decide if images/diagrams are needed for THIS blog. Rules: - Max 3 images total. - Each image must materially improve understanding (diagram/flow/table-like visual). - Insert placeholders exactly: [[IMAGE_1]], [[IMAGE_2]], [[IMAGE_3]]. - If no images needed: md_with_placeholders must equal input and images=[]. - Avoid decorative images; prefer technical diagrams with short labels. Return strictly GlobalImagePlan.

[[IMAGE_1]] Diagram of the self‑attention computation: input X (N×d_model) projected to Q, K, V; scaled dot‑product QKᵀ/√d_k; softmax; multiplied by V. Include dimension labels (d_model, d_k, d_v) and sequence length N.

[[IMAGE_2]] Table/bar chart comparing FLOP counts of self‑attention (4·N²·d) versus 3×3 convolution (9·d²·N) for N=256, d=512, highlighting the ~4.5× lower per‑token cost of attention.

[[IMAGE_3]] Flowchart of the debugging workflow: forward hook → store attention matrix → TensorBoard histogram → backward hook → gradient check → NaN assertion after softmax → enable anomaly detection.

GlobalImagePlan