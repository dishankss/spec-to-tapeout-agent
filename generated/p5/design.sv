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

logic signed [2*WIDTH-1:0] mult_0;
logic signed [2*WIDTH-1:0] mult_1;
logic signed [2*WIDTH-1:0] mult_2;
logic signed [2*WIDTH-1:0] mult_3;
logic signed [2*WIDTH-1:0] mult_4;
logic signed [2*WIDTH-1:0] mult_5;
logic signed [2*WIDTH-1:0] mult_6;
logic signed [2*WIDTH-1:0] mult_7;

logic signed [2*WIDTH+3:0] mult_0_ext;
logic signed [2*WIDTH+3:0] mult_1_ext;
logic signed [2*WIDTH+3:0] mult_2_ext;
logic signed [2*WIDTH+3:0] mult_3_ext;
logic signed [2*WIDTH+3:0] mult_4_ext;
logic signed [2*WIDTH+3:0] mult_5_ext;
logic signed [2*WIDTH+3:0] mult_6_ext;
logic signed [2*WIDTH+3:0] mult_7_ext;

logic signed [2*WIDTH+3:0] sum_0;
logic signed [2*WIDTH+3:0] sum_1;
logic signed [2*WIDTH+3:0] sum_2;
logic signed [2*WIDTH+3:0] sum_3;
logic signed [2*WIDTH+3:0] sum_4;
logic signed [2*WIDTH+3:0] sum_5;
logic signed [2*WIDTH+3:0] sum_total;

assign mult_0 = $signed(A[0]) * $signed(B[0]);
assign mult_1 = $signed(A[1]) * $signed(B[1]);
assign mult_2 = $signed(A[2]) * $signed(B[2]);
assign mult_3 = $signed(A[3]) * $signed(B[3]);
assign mult_4 = $signed(A[4]) * $signed(B[4]);
assign mult_5 = $signed(A[5]) * $signed(B[5]);
assign mult_6 = $signed(A[6]) * $signed(B[6]);
assign mult_7 = $signed(A[7]) * $signed(B[7]);

assign mult_0_ext = {{4{mult_0[2*WIDTH-1]}}, mult_0};
assign mult_1_ext = {{4{mult_1[2*WIDTH-1]}}, mult_1};
assign mult_2_ext = {{4{mult_2[2*WIDTH-1]}}, mult_2};
assign mult_3_ext = {{4{mult_3[2*WIDTH-1]}}, mult_3};
assign mult_4_ext = {{4{mult_4[2*WIDTH-1]}}, mult_4};
assign mult_5_ext = {{4{mult_5[2*WIDTH-1]}}, mult_5};
assign mult_6_ext = {{4{mult_6[2*WIDTH-1]}}, mult_6};
assign mult_7_ext = {{4{mult_7[2*WIDTH-1]}}, mult_7};

assign sum_0 = mult_0_ext + mult_1_ext;
assign sum_1 = mult_2_ext + mult_3_ext;
assign sum_2 = mult_4_ext + mult_5_ext;
assign sum_3 = mult_6_ext + mult_7_ext;

assign sum_4 = sum_0 + sum_1;
assign sum_5 = sum_2 + sum_3;

assign sum_total = sum_4 + sum_5;

always @(posedge clk) begin
    if (rst) begin
        dot_out <= '0;
        valid   <= 1'b0;
    end else begin
        dot_out <= sum_total;
        valid   <= 1'b1;
    end
end

endmodule
