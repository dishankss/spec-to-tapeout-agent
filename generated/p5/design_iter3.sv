module dot_product #(
    parameter int N = 8,
    parameter int WIDTH = 8
) (
    input  logic clk,
    input  logic rst,
    input  logic signed [N-1:0][WIDTH-1:0] A,
    input  logic signed [N-1:0][WIDTH-1:0] B,
    output logic signed [2*WIDTH+3:0] dot_out,
    output logic valid
);

    localparam int PROD_W = 2 * WIDTH;
    localparam int OUT_W  = 2 * WIDTH + 4;
    localparam int EXT_W  = OUT_W - PROD_W;

    logic signed [PROD_W-1:0] prod_reg [0:N-1];
    logic signed [OUT_W-1:0]  sum_next;
    logic signed [OUT_W-1:0]  sum_reg;
    logic [1:0]               stage_count;
    integer                   i;

    always_comb begin
        sum_next = '0;
        for (i = 0; i < N; i = i + 1) begin
            sum_next = sum_next + {{EXT_W{prod_reg[i][PROD_W-1]}}, prod_reg[i]};
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < N; i = i + 1) begin
                prod_reg[i] <= '0;
            end
            sum_reg     <= '0;
            dot_out     <= '0;
            valid       <= 1'b0;
            stage_count <= 2'd0;
        end else begin
            valid <= 1'b0;

            case (stage_count)
                2'd0: begin
                    for (i = 0; i < N; i = i + 1) begin
                        prod_reg[i] <= $signed(A[i]) * $signed(B[i]);
                    end
                    stage_count <= 2'd1;
                end

                2'd1: begin
                    sum_reg     <= sum_next;
                    stage_count <= 2'd2;
                end

                2'd2: begin
                    dot_out     <= sum_reg;
                    valid       <= 1'b1;
                    stage_count <= 2'd3;
                end

                default: begin
                    stage_count <= 2'd3;
                end
            endcase
        end
    end

endmodule
