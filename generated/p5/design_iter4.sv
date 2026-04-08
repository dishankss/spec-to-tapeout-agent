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

    localparam int PROD_WIDTH = 2*WIDTH;
    localparam int ACC_WIDTH  = 2*WIDTH + 4;

    logic signed [PROD_WIDTH-1:0] product_reg [0:N-1];
    logic signed [ACC_WIDTH-1:0]  sum_next;
    logic [1:0]                   stage;

    integer i;

    always_comb begin
        sum_next = '0;
        for (i = 0; i < N; i = i + 1) begin
            sum_next = sum_next
                     + $signed({{(ACC_WIDTH-PROD_WIDTH){product_reg[i][PROD_WIDTH-1]}}, product_reg[i]});
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < N; i = i + 1) begin
                product_reg[i] <= '0;
            end
            dot_out <= '0;
            valid   <= 1'b0;
            stage   <= 2'd0;
        end else begin
            valid <= 1'b0;

            case (stage)
                2'd0: begin
                    for (i = 0; i < N; i = i + 1) begin
                        product_reg[i] <= A[i] * B[i];
                    end
                    stage <= 2'd1;
                end

                2'd1: begin
                    dot_out <= sum_next;
                    stage   <= 2'd2;
                end

                2'd2: begin
                    valid <= 1'b1;
                    stage <= 2'd3;
                end

                default: begin
                    stage <= 2'd3;
                end
            endcase
        end
    end

endmodule
